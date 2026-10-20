"""Read-only reconciliation of an uncertain course submission; never resubmit."""
import argparse
import copy
import json
from pathlib import Path
from .course_client import CourseClient, CourseClientError, MAX_REQUEST
from .course_protocol import (decode_json, validate_course_request, validate_course_result,
                              CourseContract, CourseProtocolError)
from .deepagent_contract import payload_digest


def reconcile_course_run(client, request):
    """Query the original run against its expected request, without a POST.

    A missing volatile cache entry cannot establish whether execution occurred.
    The caller must consult its own authorized, persisted business history.
    """
    try:
        contract = CourseContract()
        validate_course_request(request, contract)
        request = copy.deepcopy(request)
    except (CourseProtocolError, KeyError, TypeError, ValueError, OSError):
        raise CourseClientError('INVALID_REQUEST') from None
    report = {
        'scope': 'COURSE_SYNTHETIC_RECONCILIATION', 'recoveryVersion': 'course-recovery-v1',
        'runId': request['runId'], 'requestDigest': payload_digest(request),
        'lookupStatus': 'LOOKUP_FAILED', 'result': None, 'error': None,
        'executionOccurred': None, 'businessHistoryRequired': True,
        'submissionAttemptedByRecovery': False, 'resubmissionAuthorized': False,
        'sourceAuthenticityVerified': False, 'clinicalValidityAssessed': False,
    }
    try:
        result = client.result(request['runId'], expected_request=copy.deepcopy(request))
        validate_course_result(result, request, contract)
        report['result'] = copy.deepcopy(result)
    except CourseClientError as error:
        report['error'] = {'code': error.code, 'httpStatus': error.http_status}
        if error.http_status == 404 and error.code == 'RUN_NOT_FOUND':
            report['lookupStatus'] = 'CACHE_MISS'
    except CourseProtocolError as error:
        report['error'] = {'code': error.code, 'httpStatus': 200}
    else:
        report['lookupStatus'] = 'FOUND'
        # This is a validated returned DTO, not proof of authentic execution,
        # Java ownership, authorization, persistence or prior business success.
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8091')
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        # Validate the target before making any request; do not truncate a
        # previous reconciliation result or either input file.
        if args.output.exists(): raise CourseClientError('OUTPUT_EXISTS')
        if args.request.stat().st_size > MAX_REQUEST: raise CourseClientError('REQUEST_TOO_LARGE')
        request = decode_json(args.request.read_bytes())
        report = reconcile_course_run(CourseClient(args.url), request)
        with args.output.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        print(json.dumps({'lookupStatus': report['lookupStatus'],
                          'submissionAttempted': False, 'businessHistoryRequired': True}))
        return {'FOUND': 0, 'CACHE_MISS': 2, 'LOOKUP_FAILED': 1}[report['lookupStatus']]
    except (OSError, ValueError, CourseClientError) as error:
        print(json.dumps({'lookupStatus': 'REJECTED', 'code': getattr(error, 'code', 'RECOVERY_IO_OR_JSON')}))
        return 1


if __name__ == '__main__': raise SystemExit(main())
