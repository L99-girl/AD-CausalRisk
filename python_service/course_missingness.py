"""Bounded plans for original synthetic rule sensitivity to removed inputs.

No scorer, HTTP, files, imputation, model selection or runId allocation occurs.
All-history erasure prevents older observations from resurfacing in a scenario.
"""
from __future__ import annotations

import copy
import json

from .course_graph import GraphEvidenceError, _snapshot as _graph_snapshot, _digest as _graph_digest

PLAN_VERSION = 'course-missingness-plan-v1'
MODALITIES = (('COGNITION', ('mmse', 'moca', 'cdrSb'), ()),
              ('GENETICS', (), ('APOE_E4_COUNT',)),
              ('MRI', (), ('MRI_HIPPOCAMPUS_L', 'MRI_HIPPOCAMPUS_R')))
SIGNALS = (('MMSE', ('mmse',), ()), ('MOCA', ('moca',), ()), ('CDR_SB', ('cdrSb',), ()),
           ('APOE_E4_COUNT', (), ('APOE_E4_COUNT',)),
           ('MRI_HIPPOCAMPUS_L', (), ('MRI_HIPPOCAMPUS_L',)),
           ('MRI_HIPPOCAMPUS_R', (), ('MRI_HIPPOCAMPUS_R',)))
MAX_SCENARIOS = 1000


class MissingnessError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _require(condition, code):
    if not condition:
        raise MissingnessError(code)


def _snapshot(value, maximum):
    try:
        return _graph_snapshot(value, maximum)
    except GraphEvidenceError as error:
        raise MissingnessError('MISSINGNESS_' + error.code) from None


def _digest(value, maximum=6 * 1024 * 1024):
    try:
        return _graph_digest(value, maximum)
    except GraphEvidenceError as error:
        raise MissingnessError('MISSINGNESS_' + error.code) from None


def prepare_missingness_requests(requests, run_ids, *, granularity='MODALITY'):
    """Return explicit-ID scenarios; the caller decides whether to execute them.

    run_ids map to subjectCode-sorted requests and ascending bit masks. They
    must be caller-allocated, unique, and disjoint from the original runIds.
    """
    from .course_protocol import CourseContract, CourseProtocolError, validate_course_request
    from .deepagent_contract import RUN_ID_RE, payload_digest

    requests, run_ids, granularity = _snapshot([requests, run_ids, granularity], 1024 * 1024)
    _require(type(granularity) is str and granularity in ('MODALITY', 'SIGNAL'), 'GRANULARITY')
    _require(type(requests) is list and 1 <= len(requests) <= 100, 'BASE_REQUEST_COUNT')
    contract = CourseContract()
    try:
        for request in requests:
            validate_course_request(request, contract)
    except CourseProtocolError:
        raise MissingnessError('BASE_REQUEST_INVALID') from None
    _require(len({row['subjectCode'] for row in requests}) == len(requests)
             and len({row['runId'] for row in requests}) == len(requests), 'DUPLICATE_BASE_BINDING')
    _require(len({(row['dataVersion'], row['modelVersion'], row['predictionWindowMonths']) for row in requests}) == 1,
             'MIXED_BASE_VERSIONS_OR_WINDOW')
    groups = MODALITIES if granularity == 'MODALITY' else SIGNALS
    mask_count = 1 << len(groups)
    count = len(requests) * mask_count
    _require(count <= MAX_SCENARIOS, 'SCENARIO_COUNT_LIMIT')
    _require(type(run_ids) is list and len(run_ids) == count
             and all(type(value) is str and RUN_ID_RE.fullmatch(value) for value in run_ids), 'SCENARIO_RUN_IDS')
    _require(len(set(run_ids)) == count and not set(run_ids) & {row['runId'] for row in requests}, 'RUN_ID_REUSE')
    scenarios, encoded_size = [], 0
    for base in sorted(requests, key=lambda row: row['subjectCode']):
        for mask in range(mask_count):
            active = [spec for bit, spec in enumerate(groups) if mask & (1 << bit)]
            cognition = {field for _, fields, _ in active for field in fields}
            features = {name for _, _, names in active for name in names}
            body = copy.deepcopy(base)
            body['runId'] = run_ids[len(scenarios)]
            erased = {field: 0 for field in sorted(cognition)}
            for visit in body['visits']:
                for field in cognition:
                    if visit.get(field) is not None:
                        visit[field] = None
                        erased[field] += 1
            retained = [(index + 1, row) for index, row in enumerate(body['features']) if row['featureName'] not in features]
            removed_rows = len(body['features']) - len(retained)
            removed_values = sum(row['featureName'] in features and row.get('featureValue') is not None for row in body['features'])
            body['features'] = [row for _, row in retained]
            scenario = {'subjectCode': base['subjectCode'], 'baselineRunId': base['runId'],
                'baselineRequestSha256': payload_digest(base), 'mask': mask,
                'removedGroups': [name for name, _, _ in active], 'request': body,
                'requestSha256': payload_digest(body), 'erasedCognitionValues': erased,
                'removedFeatureRows': removed_rows, 'removedFeatureValues': removed_values,
                'inputChangedBeyondRunId': bool(removed_rows or sum(erased.values())),
                'sourceMap': {'visits': list(range(1, len(body['visits']) + 1)),
                              'features': [index for index, _ in retained]}}
            encoded_size += len(json.dumps(scenario, ensure_ascii=False, sort_keys=True,
                                           separators=(',', ':'), allow_nan=False).encode('utf-8'))
            _require(encoded_size <= 4 * 1024 * 1024, 'SCENARIO_BYTES_LIMIT')
            scenarios.append(scenario)
    plan = {'scope': 'COURSE_SYNTHETIC_MISSINGNESS_PLAN', 'planVersion': PLAN_VERSION,
        'granularity': granularity, 'groups': [{'name': name, 'cognitionFields': list(fields), 'featureNames': list(names)}
                                              for name, fields, names in groups],
        'dataVersion': requests[0]['dataVersion'], 'modelVersion': requests[0]['modelVersion'],
        'predictionWindowMonths': requests[0]['predictionWindowMonths'],
        'subjectCount': len(requests), 'maskCount': mask_count, 'scenarioCount': count,
        'baseRequests': requests, 'allocatedRunIds': run_ids, 'scenarios': scenarios,
        'removalPolicy': 'ERASE_ALL_SUPPLIED_HISTORY_NO_IMPUTATION',
        'scoringExecutedByThisCall': False, 'networkUsedByThisCall': False,
        'persisted': False, 'alternativeModelSelected': False, 'clinicalConfidence': None}
    _digest(plan)
    return plan


def validate_missingness_plan(plan):
    """Rebuild the exact plan, including masks, source maps, flags and bodies."""
    plan = _snapshot(plan, 6 * 1024 * 1024)
    _require(type(plan) is dict and {'baseRequests', 'allocatedRunIds', 'granularity'} <= plan.keys(), 'PLAN_FIELDS')
    expected = prepare_missingness_requests(plan['baseRequests'], plan['allocatedRunIds'], granularity=plan['granularity'])
    _require(_digest(plan) == _digest(expected), 'PLAN_RECONSTRUCTION_MISMATCH')
    return expected
