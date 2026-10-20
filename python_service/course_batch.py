"""Explicit synthetic CSV-to-HTTP-to-report runs; no automatic retry or resume.

Files are local lab receipts, not Java tasks, database import or authorization.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
from uuid import uuid4
from .course_client import CourseClient, CourseClientError, MAX_REQUEST, MAX_RESPONSE
from .course_csv import prepare_csv, quality_summary, CsvPreviewError
from .course_protocol import (CourseContract, CourseProtocolError, decode_json,
                              validate_course_request, validate_course_result)
from .course_report import build_course_report, render_course_html, CourseReportError
from .deepagent_contract import payload_digest

MAX_PLAN = 256 * 1024
MAX_JOURNAL = 512 * 1024
FLAGS = {'businessPersisted': False, 'sourceAuthenticityVerified': False,
         'clinicalValidityAssessed': False, 'automaticResumeSupported': False}


class CourseBatchError(ValueError):
    def __init__(self, code): self.code = code; super().__init__(code)


def require(condition, code):
    if not condition: raise CourseBatchError(code)


def encoded(value):
    try: return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (TypeError, ValueError, RecursionError, UnicodeError): raise CourseBatchError('BATCH_JSON') from None


def sha(raw): return hashlib.sha256(raw).hexdigest()


def read_bytes(path, limit):
    require(not path.is_symlink(), 'BATCH_FILE_SYMLINK')
    with path.open('rb') as stream: raw = stream.read(limit + 1)
    require(len(raw) <= limit, 'BATCH_FILE_SIZE')
    return raw


def read_json(path, limit=MAX_PLAN): return decode_json(read_bytes(Path(path), limit))


def write_new(path, raw):
    with path.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    return sha(raw)


def prepare_course_batch(preview_input, run_ids):
    preview, requests = prepare_csv(preview_input)
    require(preview['status'] == 'PREVIEW_ONLY', 'BATCH_CSV_INVALID')
    subjects = {request['subjectCode'] for request in requests}
    require(isinstance(run_ids, dict) and set(run_ids) == subjects, 'BATCH_RUN_ID_MAPPING')
    require(all(isinstance(value, str) for value in run_ids.values()) and len(set(run_ids.values())) == len(subjects), 'BATCH_RUN_ID_MAPPING')
    contract = CourseContract()
    requests = sorted(requests, key=lambda row: row['subjectCode'])
    for request in requests:
        request['runId'] = run_ids[request['subjectCode']]
        require(request['runId'] != 'run-csv-' + request['subjectCode'], 'BATCH_PLACEHOLDER_RUN_ID')
        validate_course_request(request, contract)
    plan = {'scope': 'COURSE_SYNTHETIC_BATCH_PLAN', 'planVersion': 'course-batch-v1',
            'csvSourceDigest': preview['requestDigest'], 'contractSha256': contract.sha256,
            'requests': requests, 'quality': [quality_summary(request) for request in requests], **FLAGS}
    plan['planDigest'] = sha(encoded(plan))
    return validate_batch_plan(plan)


def validate_batch_plan(plan):
    require(len(encoded(plan)) + 1 <= MAX_PLAN, 'BATCH_PLAN_SIZE')
    keys = {'scope', 'planVersion', 'csvSourceDigest', 'contractSha256', 'requests', 'quality', 'planDigest'} | set(FLAGS)
    require(isinstance(plan, dict) and set(plan) == keys, 'BATCH_PLAN_FIELDS')
    require(plan['scope'] == 'COURSE_SYNTHETIC_BATCH_PLAN' and plan['planVersion'] == 'course-batch-v1', 'BATCH_SCOPE')
    require(all(plan[key] is value for key, value in FLAGS.items()), 'BATCH_SCOPE')
    require(isinstance(plan['csvSourceDigest'], str) and re.fullmatch('[0-9a-f]{64}', plan['csvSourceDigest']), 'BATCH_SOURCE_DIGEST')
    contract = CourseContract()
    require(plan['contractSha256'] == contract.sha256, 'BATCH_CONTRACT')
    requests = plan['requests']
    require(isinstance(requests, list) and 1 <= len(requests) <= 200, 'BATCH_REQUESTS')
    for request in requests:
        validate_course_request(request, contract)
        require(len(encoded(request)) <= MAX_REQUEST, 'BATCH_REQUEST_SIZE')
        require(request['runId'] != 'run-csv-' + request['subjectCode'], 'BATCH_PLACEHOLDER_RUN_ID')
    subjects, runs = [row['subjectCode'] for row in requests], [row['runId'] for row in requests]
    require(subjects == sorted(set(subjects)) and len(set(runs)) == len(runs), 'BATCH_BINDINGS')
    require(len({(row['dataVersion'], row['predictionWindowMonths']) for row in requests}) == 1, 'BATCH_VERSIONS')
    require(encoded(plan['quality']) == encoded([quality_summary(request) for request in requests]), 'BATCH_QUALITY')
    body = {key: value for key, value in plan.items() if key != 'planDigest'}
    require(plan['planDigest'] == sha(encoded(body)), 'BATCH_PLAN_DIGEST')
    return copy.deepcopy(plan)


def execute_course_batch(plan, client, output_directory):
    """Caller explicitly invokes execution. Every intent is flushed before POST."""
    plan = validate_batch_plan(plan); directory = Path(output_directory)
    directory.mkdir(exist_ok=False)  # An existing run cannot be silently resumed.
    write_new(directory/'plan.json', encoded(plan) + b'\n')
    contract = CourseContract()
    with (directory/'events.jsonl').open('xb') as journal:
        def event(kind, **fields):
            journal.write(encoded({'event': kind, **fields}) + b'\n'); journal.flush(); os.fsync(journal.fileno())
        event('START', planDigest=plan['planDigest'])
        try: client.health()
        except CourseClientError as error:
            event('HEALTH_FAILED', code=error.code, httpStatus=error.http_status)
        else:
            for index, request in enumerate(plan['requests'], 1):
                run_id = request['runId']; trace = 'batch-' + uuid4().hex
                event('INTENT', index=index, runId=run_id, requestDigest=payload_digest(request), traceId=trace)
                try:
                    result = client.create(copy.deepcopy(request), trace_id=trace)
                    validate_course_result(result, request, contract)
                except CourseClientError as error:
                    event('FAILED', index=index, runId=run_id, code=error.code,
                          httpStatus=error.http_status, outcomeUnknown=error.request_outcome_unknown)
                    break
                except CourseProtocolError as error:
                    event('FAILED', index=index, runId=run_id, code=error.code, httpStatus=200, outcomeUnknown=True)
                    break
                result_hash = write_new(directory/f'{index:03d}.result.json', encoded(result) + b'\n')
                event('RESULT', index=index, runId=run_id, resultSha256=result_hash)
                try:
                    report = build_course_report(request, result)
                    html = render_course_html(request, result)
                    report_hash = write_new(directory/f'{index:03d}.report.json', encoded(report) + b'\n')
                    html_hash = write_new(directory/f'{index:03d}.report.html', html.encode('utf-8'))
                except CourseReportError as error:
                    event('REPORT_FAILED', index=index, runId=run_id, code=error.code)
                    break
                event('REPORT', index=index, runId=run_id, reportSha256=report_hash, htmlSha256=html_hash)
        event('FINISH')
    summary = inspect_course_batch(directory)
    write_new(directory/'summary.json', encoded(summary) + b'\n')
    return summary


def inspect_course_batch(directory):
    """Validate local receipts only; never send or retry any request."""
    directory = Path(directory); plan = validate_batch_plan(read_json(directory/'plan.json'))
    raw = read_bytes(directory/'events.jsonl', MAX_JOURNAL)
    lines = raw.splitlines(keepends=True); truncated = bool(raw and not raw.endswith(b'\n'))
    if truncated: lines = lines[:-1]  # A partial last write cannot acknowledge a result.
    require(0 < len(lines) <= 4 * len(plan['requests']) + 3, 'BATCH_JOURNAL')
    events = [decode_json(line) for line in lines]
    require(events[0] == {'event': 'START', 'planDigest': plan['planDigest']}, 'BATCH_JOURNAL')
    items = [{'index': index, 'runId': request['runId'], 'status': 'NOT_ATTEMPTED', 'reportStatus': 'MISSING'}
             for index, request in enumerate(plan['requests'], 1)]
    active, next_index, finished, stopped = None, 1, False, False
    contract = CourseContract()
    fields = {'INTENT': {'index','runId','requestDigest','traceId'}, 'RESULT': {'index','runId','resultSha256'},
              'FAILED': {'index','runId','code','httpStatus','outcomeUnknown'},
              'REPORT': {'index','runId','reportSha256','htmlSha256'}, 'REPORT_FAILED': {'index','runId','code'},
              'HEALTH_FAILED': {'code','httpStatus'}, 'FINISH': set()}
    for entry in events[1:]:
        kind = entry.get('event')
        require(not finished and kind in fields and set(entry) == fields[kind] | {'event'}, 'BATCH_JOURNAL')
        if 'code' in entry:
            require(isinstance(entry['code'], str) and re.fullmatch('[A-Z][A-Z0-9_]{0,63}', entry['code']), 'BATCH_JOURNAL')
        if 'httpStatus' in entry:
            require(entry['httpStatus'] is None or (type(entry['httpStatus']) is int and 100 <= entry['httpStatus'] <= 599), 'BATCH_JOURNAL')
        if kind == 'HEALTH_FAILED':
            require(next_index == 1 and active is None and not stopped, 'BATCH_JOURNAL'); stopped = True
            continue
        if kind == 'FINISH':
            require(active is None, 'BATCH_JOURNAL'); finished = True; continue
        index = entry['index']
        require(type(index) is int and 1 <= index <= len(items), 'BATCH_JOURNAL')
        request, item = plan['requests'][index - 1], items[index - 1]
        require(entry['runId'] == request['runId'], 'BATCH_JOURNAL')
        if kind == 'INTENT':
            require(not stopped and active is None and index == next_index, 'BATCH_JOURNAL')
            require(entry['requestDigest'] == payload_digest(request) and isinstance(entry['traceId'], str)
                    and re.fullmatch('[A-Za-z0-9._-]{1,64}', entry['traceId']), 'BATCH_JOURNAL')
            item['status'] = 'UNKNOWN'; active = index; next_index += 1
        elif kind == 'RESULT':
            require(not stopped and active == index and item['status'] == 'UNKNOWN', 'BATCH_JOURNAL')
            result_raw = read_bytes(directory/f'{index:03d}.result.json', MAX_RESPONSE + 1)
            require(sha(result_raw) == entry['resultSha256'], 'BATCH_RESULT_DIGEST')
            result = decode_json(result_raw); validate_course_result(result, request, contract)
            item['status'] = result['status']
        elif kind in ('REPORT', 'REPORT_FAILED'):
            require(not stopped and active == index and item['status'] in ('COMPLETED','BLOCKED'), 'BATCH_JOURNAL')
            if kind == 'REPORT':
                for name, key in (('json','reportSha256'), ('html','htmlSha256')):
                    require(sha(read_bytes(directory/f'{index:03d}.report.{name}', MAX_RESPONSE * 2)) == entry[key], 'BATCH_REPORT_DIGEST')
                item['reportStatus'] = 'READY'
            else: item['reportStatus'] = 'FAILED'; stopped = True
            active = None
        else:
            require(not stopped and active == index and item['status'] == 'UNKNOWN' and type(entry['outcomeUnknown']) is bool, 'BATCH_JOURNAL')
            item['status'] = 'UNKNOWN' if entry['outcomeUnknown'] else 'FAILED'
            item['error'] = {'code': entry['code'], 'httpStatus': entry['httpStatus']}
            active = None; stopped = True
    counts = {status: sum(item['status'] == status for item in items)
              for status in ('COMPLETED','BLOCKED','FAILED','UNKNOWN','NOT_ATTEMPTED')}
    complete = finished and not truncated and all(item['reportStatus'] == 'READY' for item in items)
    return {'scope': 'COURSE_SYNTHETIC_BATCH_RECEIPT', 'planDigest': plan['planDigest'],
            'status': 'FINISHED' if complete else 'HALTED' if finished else 'INCOMPLETE',
            'counts': counts, 'items': items, 'journalTailIncomplete': truncated,
            'businessHistoryRequired': True, 'resubmissionAuthorized': False, **FLAGS}


def main():
    parser = argparse.ArgumentParser(description=__doc__); modes = parser.add_subparsers(dest='mode', required=True)
    prepare = modes.add_parser('prepare'); prepare.add_argument('--input', type=Path, required=True)
    prepare.add_argument('--output', type=Path, required=True)
    execute = modes.add_parser('execute'); execute.add_argument('--plan', type=Path, required=True)
    execute.add_argument('--url', default='http://127.0.0.1:8091'); execute.add_argument('--output', type=Path, required=True)
    inspect = modes.add_parser('inspect'); inspect.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.mode == 'prepare':
            body = read_json(args.input)
            require(set(body) == {'previewInput','runIds'}, 'BATCH_INPUT_FIELDS')
            plan = prepare_course_batch(body['previewInput'], body['runIds'])
            write_new(args.output, encoded(plan) + b'\n')
            print(json.dumps({'status': 'PREPARED', 'subjects': len(plan['requests']), 'networkRequests': 0})); return 0
        result = execute_course_batch(read_json(args.plan), CourseClient(args.url), args.output) if args.mode == 'execute' else inspect_course_batch(args.directory)
        print(json.dumps({key: result[key] for key in ('status','counts','businessHistoryRequired','resubmissionAuthorized')}))
        return 0 if result['status'] == 'FINISHED' else 2
    except KeyboardInterrupt:
        print(json.dumps({'status': 'INTERRUPTED', 'automaticResumeSupported': False})); return 130
    except (OSError, ValueError, CourseClientError) as error:
        print(json.dumps({'status': 'REJECTED', 'code': getattr(error, 'code', 'BATCH_IO_OR_JSON')})); return 1


if __name__ == '__main__': raise SystemExit(main())
