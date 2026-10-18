"""Bounded, non-persistent preview of the three shipped course CSV tables.

Only declared synthetic data is accepted. No files, models, HTTP calls or scores.
The course integer APOE convention and continuous cognition ranges are retained.
"""
import csv
from datetime import date
import hashlib
import io
import json
import math
import re
from .deepagent_contract import CONTRACT_VERSION, MODEL_VERSION, FEATURES, validate_request

TABLES = {
    'subjects': ('subjectCode', 'alias', 'status'),
    'visits': ('subjectCode', 'visitCode', 'visitDate', 'mmse', 'moca', 'cdrSb'),
    'features': ('subjectCode', 'featureName', 'featureValue', 'recordedAt', 'unit'),
}
ROW_LIMITS = {'subjects': 200, 'visits': 1000, 'features': 2000}
RULE_VERSION = 'course-csv-preflight-1'
QUALITY_VERSION = 'synthetic-qa-v1'
MAX_BYTES = 30000
MAX_ISSUES = 200
SCOPE = 'COURSE_SYNTHETIC_PREVIEW'


class CsvPreviewError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise CsvPreviewError(code)


def located_rows(reader):
    while True:
        start = reader.line_num + 1
        try:
            values = next(reader)
        except StopIteration:
            return
        yield start, values


def quality_summary(payload):
    """Original fusion/scorer quality gates, with no score-tool invocation.

    Callers must supply a valid original AgentRequest. Parity is tested against
    original run_workflow; these fields are preview evidence, not AgentResult.
    """
    validate_request(payload)
    visits = sorted(payload['visits'], key=lambda row: (row['visitDate'], row['visitCode']))
    latest = visits[-1] if visits else None
    cutoff = latest['visitDate'] if latest else None
    eligible = [row for row in payload['features'] if cutoff and row['recordedAt'] <= cutoff]
    selected, seen, conflicts = {}, {}, False
    for row in sorted(eligible, key=lambda row: row['recordedAt']):
        key = (row['featureName'], row['recordedAt'])
        conflicts |= key in seen and seen[key] != row['featureValue']
        seen[key] = row['featureValue']
        if row['featureValue'] is not None:
            selected[row['featureName']] = row
    missing = [name for name in sorted(FEATURES) if name not in selected]
    reasons = []
    if not latest or not any(latest.get(key) is not None for key in ('mmse', 'moca', 'cdrSb')):
        reasons.append('CORE_COGNITION_MISSING')
    if latest and sum(row['visitDate'] == cutoff for row in visits) > 1:
        reasons.append('AMBIGUOUS_INDEX_VISIT')
    if conflicts:
        reasons.append('CONFLICTING_FEATURE_VALUES')
    if payload['predictionWindowMonths'] != 24:
        reasons.append('UNSUPPORTED_WINDOW')
    excluded = len(payload['features']) - len(eligible)
    warnings = []
    if excluded:
        warnings.append('POST_INDEX_FEATURES_EXCLUDED')
    if missing:
        warnings.append('MISSING_MODALITIES')
    if latest and any(latest.get(key) is None for key in ('mmse', 'moca', 'cdrSb')):
        warnings.append('PARTIAL_COGNITION')
    return {'subjectCode': payload['subjectCode'], 'qualityStatus': 'BLOCKED' if reasons else 'WARN' if warnings else 'PASS',
            'qualityRuleVersion': QUALITY_VERSION, 'indexDate': cutoff, 'missingModalities': missing,
            'excludedPostIndexFeatures': excluded, 'blockingReasons': reasons, 'warningCodes': warnings,
            'riskScore': None, 'predictionProduced': False}


def prepare_csv(payload):
    """Return (safe preview, typed requests). Invalid batch has no requests.

    Internal typed requests retain caller input only in memory; the HTTP preview
    returns the safe first item and never forwards/executes/persists the second.
    """
    require(isinstance(payload, dict) and set(payload) == {'input_mode', 'dataVersion', 'predictionWindowMonths', 'tables'}, 'PREVIEW_FIELDS')
    require(payload['input_mode'] == 'SYNTHETIC_TEST', 'SYNTHETIC_ONLY')
    version, window, texts = payload['dataVersion'], payload['predictionWindowMonths'], payload['tables']
    require(isinstance(version, str) and version.startswith('demo-') and len(version) <= 100, 'DATA_VERSION')
    require(type(window) is int and 6 <= window <= 60, 'PREDICTION_WINDOW')
    require(isinstance(texts, dict) and set(texts) == set(TABLES) and all(isinstance(value, str) for value in texts.values()), 'TABLES_REQUIRED')
    try:
        version.encode('utf-8')
        size = sum(len(value.encode('utf-8')) for value in texts.values())
    except UnicodeError:
        raise CsvPreviewError('CSV_ENCODING') from None
    require(0 < size <= MAX_BYTES, 'CSV_SIZE')
    issues, issue_count = [], 0
    counts, parsed = {}, {name: [] for name in TABLES}

    def issue(table, row, field, code, severity='ERROR'):
        nonlocal issue_count
        issue_count += 1
        if len(issues) < MAX_ISSUES:
            issues.append({'table': table, 'row': row, 'field': field, 'code': code, 'severity': severity})

    error_count = 0
    for table, columns in TABLES.items():
        text = texts[table]
        # One optional leading UTF-8 BOM is accepted, never guessed encodings.
        if text.startswith('\ufeff'):
            text = text[1:]
        if '\x00' in text:
            issue(table, 1, 'table', 'NUL_CHARACTER'); error_count += 1
        reader = csv.reader(io.StringIO(text, newline=''), strict=True)
        try:
            header = next(reader, [])
            if header != list(columns):
                issue(table, 1, 'header', 'HEADER_EXACT_REQUIRED'); error_count += 1
                counts[table] = 0
                continue
            row_count = 0
            for start, values in located_rows(reader):
                row_count += 1
                if row_count > ROW_LIMITS[table]:
                    issue(table, start, 'table', 'ROW_LIMIT'); error_count += 1
                    break
                if len(values) != len(columns):
                    issue(table, start, 'row', 'COLUMN_COUNT'); error_count += 1
                    continue
                row = dict(zip(columns, values)); valid = True

                def bad(field, code):
                    nonlocal valid, error_count
                    issue(table, start, field, code); valid = False; error_count += 1

                if not re.fullmatch(r'DEMO-[A-Za-z0-9-]{1,45}', row['subjectCode']):
                    bad('subjectCode', 'SYNTHETIC_ALIAS_REQUIRED')
                if table == 'subjects':
                    if not row['alias'].strip() or len(row['alias']) > 100:
                        bad('alias', 'ALIAS_REQUIRED_MAX_100')
                    if row['status'] not in ('ACTIVE', 'ARCHIVED'):
                        bad('status', 'SUBJECT_STATUS')
                else:
                    date_field = 'visitDate' if table == 'visits' else 'recordedAt'
                    try:
                        raw = row[date_field]
                        if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', raw) or date.fromisoformat(raw) > date.today():
                            raise ValueError()
                    except ValueError:
                        bad(date_field, 'DATE_INVALID_OR_FUTURE')
                    if table == 'visits':
                        if not row['visitCode'].strip() or len(row['visitCode']) > 50:
                            bad('visitCode', 'VISIT_CODE')
                        numeric = {'mmse': (0, 30), 'moca': (0, 30), 'cdrSb': (0, 18)}
                    else:
                        name = row['featureName']
                        if name not in FEATURES:
                            bad('featureName', 'FEATURE_NOT_ALLOWED')
                        elif row['unit'] != ('count' if name == 'APOE_E4_COUNT' else 'normalized'):
                            bad('unit', 'UNIT_MISMATCH')
                        numeric = {'featureValue': (0, 2 if name == 'APOE_E4_COUNT' else 1)}
                    for field, (lower, upper) in numeric.items():
                        raw = row[field]
                        if raw == '':
                            row[field] = None
                            continue
                        try:
                            if raw != raw.strip() or not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', raw):
                                raise ValueError()
                            value = float(raw)
                            if not math.isfinite(value) or not lower <= value <= upper:
                                raise ValueError()
                            if table == 'features' and row['featureName'] == 'APOE_E4_COUNT':
                                if raw not in ('0', '1', '2'):
                                    raise ValueError()
                                value = int(raw)
                            row[field] = value
                        except ValueError:
                            bad(field, 'NUMBER_INVALID_OR_RANGE')
                if valid:
                    parsed[table].append((start, row))
            counts[table] = row_count
        except csv.Error:
            issue(table, reader.line_num or 1, 'row', 'CSV_SYNTAX'); error_count += 1
            counts[table] = len(parsed[table])
    if not parsed['subjects'] and not counts.get('subjects'):
        issue('subjects', 1, 'table', 'SUBJECTS_REQUIRED'); error_count += 1
    subjects, requests, keys = {}, {}, set()
    for line, row in parsed['subjects']:
        sid = row['subjectCode']
        if sid in subjects:
            issue('subjects', line, 'subjectCode', 'DUPLICATE_SUBJECT'); error_count += 1
        subjects[sid] = row
        requests[sid] = {'contractVersion': CONTRACT_VERSION, 'modelVersion': MODEL_VERSION,
                         'runId': 'run-csv-' + sid, 'subjectCode': sid, 'dataVersion': version,
                         'predictionWindowMonths': window, 'visits': [], 'features': []}
    feature_keys = {}
    for table in ('visits', 'features'):
        for line, row in parsed[table]:
            sid = row['subjectCode']
            if sid not in requests:
                issue(table, line, 'subjectCode', 'SUBJECT_NOT_IN_BATCH'); error_count += 1
                continue
            if table == 'visits':
                key = (sid, row['visitCode'])
                if key in keys:
                    issue(table, line, 'visitCode', 'DUPLICATE_SUBJECT_VISIT'); error_count += 1
                keys.add(key)
            else:
                key = (sid, row['featureName'], row['recordedAt'])
                if key in feature_keys and feature_keys[key] == row['featureValue']:
                    issue(table, line, 'featureName', 'REPEATED_SAME_VALUE', 'WARN')
                feature_keys[key] = row['featureValue']
            requests[sid][table].append({key: value for key, value in row.items() if key != 'subjectCode'})
        maximum = 100 if table == 'visits' else 500
        for sid, request in requests.items():
            if len(request[table]) > maximum:
                issue(table, 1, 'table', 'SUBJECT_RECORD_LIMIT'); error_count += 1
    # The hash binds exact text and declared data version/window; it is neither
    # an import token nor persisted idempotency, authenticity or authorization.
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()
    quality = [quality_summary(requests[sid]) for sid in sorted(requests)] if not error_count else []
    totals = {status: sum(row['qualityStatus'] == status for row in quality) for status in ('PASS', 'WARN', 'BLOCKED')}
    report = {'scope': SCOPE, 'status': 'INVALID' if error_count else 'PREVIEW_ONLY',
              'previewRuleVersion': RULE_VERSION, 'qualityRuleVersion': QUALITY_VERSION,
              'dataVersion': version, 'requestDigest': digest, 'rows': counts,
              'errorCount': error_count, 'issueCount': issue_count, 'issues': issues,
              'issuesTruncated': issue_count > len(issues), 'qualityCounts': totals, 'subjects': quality,
              'persisted': False, 'modelExecuted': False, 'predictionProduced': False,
              'commitSupported': False, 'clinicalValidityAssessed': False}
    return report, list(requests.values()) if not error_count else []


def preview_csv(payload):
    return prepare_csv(payload)[0]
