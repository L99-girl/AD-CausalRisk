"""Bounded, content-bound review of the original synthetic course output.

No scoring, HTTP, model loading, business review or arbitrary medical-text
classification. Acceptance never establishes clinical use or authenticity.
"""
import hashlib
import json
from pathlib import Path

from .course_graph import GraphEvidenceError, _digest, _snapshot
from .course_protocol import CourseContract, CourseProtocolError, validate_course_result

REVIEW_VERSION = 'course-output-review-v1'
MAX_REQUEST_BYTES = 128 * 1024
MAX_RESULT_BYTES = 2 * 1024 * 1024
POLICY_FILES = ('course_safety.py', 'course_protocol.py', 'course_graph.py',
                'course_fusion.py', 'deepagent_contract.py')


def _policy_digest():
    root = Path(__file__).resolve().parent
    hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in POLICY_FILES}
    return hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode('ascii')).hexdigest()


def review_course_output(request, result):
    """Return a safe review record; invalid content is never echoed or repaired.

    Digests identify supplied JSON and local policy files, not their provenance
    or an authenticated upstream execution. A BLOCKED result may pass review
    while having no prediction. The human/business review remains outstanding.
    """
    record = {'reviewVersion': REVIEW_VERSION, 'scope': 'FIXED_COURSE_RULE_OUTPUT',
              'status': 'REJECTED', 'requestSha256': None, 'resultSha256': None,
              'contractSha256': None, 'policySha256': None, 'findings': [],
              'predictionAvailable': False, 'reviewRequired': True,
              'manualReviewCompleted': False, 'clinicalUseAllowed': False,
              'clinicalValidityEstablished': False, 'causalEffectIdentified': False,
              'sourceAuthenticityVerified': False, 'upstreamExecutionVerified': False,
              'modelExecutedByReview': False, 'persisted': False}
    try:
        # Size-check serialization before copying. Snapshot/digest agreement
        # detects mutations during copying; validation uses only owned values.
        request = _snapshot(request, MAX_REQUEST_BYTES)
        record['requestSha256'] = _digest(request, MAX_REQUEST_BYTES)
        result = _snapshot(result, MAX_RESULT_BYTES)
        record['resultSha256'] = _digest(result, MAX_RESULT_BYTES)
        contract = CourseContract()
        record['contractSha256'] = contract.sha256
        record['policySha256'] = _policy_digest()
        validate_course_result(result, request, contract)
    except GraphEvidenceError as error:
        code = {'GRAPH_INPUT_SIZE': 'REVIEW_INPUT_SIZE', 'GRAPH_INPUT_CHANGED': 'REVIEW_INPUT_CHANGED'}.get(
            error.code, 'REVIEW_INPUT_JSON')
        record['findings'] = [{'code': code}]
    except CourseProtocolError as error:
        record['findings'] = [{'code': error.code}]
    except OSError:
        record['findings'] = [{'code': 'REVIEW_POLICY_UNAVAILABLE'}]
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        record['findings'] = [{'code': 'REVIEW_INPUT_INVALID'}]
    else:
        record['status'] = 'ACCEPTED'
        record['predictionAvailable'] = result['status'] == 'COMPLETED'
    return record
