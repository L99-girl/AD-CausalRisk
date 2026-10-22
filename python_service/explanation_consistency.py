"""Bounded, in-memory comparisons of declared synthetic local explanations.

Metadata declares comparability; it cannot certify source authenticity or OOF
membership. No inference, model execution, files or network operations occur.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import random
import re
from statistics import mean

SCHEMA = 'synthetic-local-explanation-v1'
COMPARISON_VERSION = 'synthetic-consistency-v1'
COURSE_TERMS = ('MMSE', 'MoCA', 'CDR_SB', 'MMSE_DELTA',
                'APOE_E4_COUNT', 'MRI_HIPPOCAMPUS')
CONTEXT = ('dataVersion', 'observationSha256', 'featureSchema', 'target',
           'outputSpace', 'reference', 'unit')
ARM = ('modelVersion', 'methodVersion', 'fold')
KEYS = {'schemaVersion', 'mode', 'subjectCode', 'values', 'missingReasons', 'evidence', *CONTEXT, *ARM}
LIMITS = {
    'modelExecuted': False, 'modelFitted': False, 'predictionProduced': False,
    'persisted': False, 'sourceAuthenticityEstablished': False,
    'outOfFoldMembershipEstablished': False, 'clinicalValidityEstablished': False,
    'researchAcceptanceEstablished': False,
}


class ConsistencyError(ValueError):
    """Invalid or incomparable declared synthetic explanations."""


def _require(condition, code):
    if not condition:
        raise ConsistencyError(code)


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _snapshot(value):
    """Bound allocation before copying even for adversarial nested containers."""
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True,
                               separators=(',', ':'), allow_nan=False)
    try:
        size = 0
        digest = hashlib.sha256()
        for chunk in encoder.iterencode(value):
            raw = chunk.encode('utf-8')
            size += len(raw)
            _require(size <= 2 * 1024 * 1024, 'INPUT_TOO_LARGE')
            digest.update(raw)
        owned = copy.deepcopy(value)
        final = hashlib.sha256()
        for chunk in encoder.iterencode(owned):
            final.update(chunk.encode('utf-8'))
        _require(digest.digest() == final.digest(), 'INPUT_CHANGED')
        return owned, final.hexdigest()
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError) as exc:
        if isinstance(exc, ConsistencyError):
            raise
        raise ConsistencyError('INVALID_JSON_INPUT') from None


def _record(value):
    _require(type(value) is dict and set(value) == KEYS, 'RECORD_FIELDS')
    _require(value['schemaVersion'] == SCHEMA and value['mode'] == 'SYNTHETIC_DEMO', 'SYNTHETIC_ONLY')
    for key in ('subjectCode', *CONTEXT, *ARM):
        text = value[key]
        _require(type(text) is str and 0 < len(text) <= 160 and text.strip() == text, 'METADATA')
    _require(value['subjectCode'].startswith('DEMO-') and len(value['subjectCode']) > 5
             and value['dataVersion'].startswith('demo-'), 'SYNTHETIC_ONLY')
    _require(re.fullmatch('[0-9a-f]{64}', value['observationSha256']) is not None, 'OBSERVATION_DIGEST')
    evidence = value['evidence']
    _require(type(evidence) is dict and set(evidence) == {'kind', 'sha256'}
             and evidence['kind'] in ('VALIDATED_COURSE_PAIR', 'CALLER_DECLARED_SYNTHETIC')
             and type(evidence['sha256']) is str
             and re.fullmatch('[0-9a-f]{64}', evidence['sha256']) is not None, 'EVIDENCE')
    terms, reasons = value['values'], value['missingReasons']
    _require(type(terms) is dict and 1 <= len(terms) <= 128 and type(reasons) is dict, 'TERM_FIELDS')
    for name, number in terms.items():
        _require(type(name) is str and 0 < len(name) <= 100 and name.strip() == name, 'TERM_NAME')
        _require(number is None or _number(number), 'TERM_NUMBER')
    _require(set(reasons) == {key for key, number in terms.items() if number is None}, 'MISSING_REASONS')
    _require(all(type(reason) is str and 0 < len(reason.strip()) <= 160 for reason in reasons.values()), 'MISSING_REASONS')
    return value


def course_explanation(request, result):
    """Adapt validated wire contributions without running a scorer.

    Contributions remain rounded pre-final-clipping rule terms, not SHAP values.
    The MRI term retains the original left-first/right-fallback semantics.
    """
    from .course_protocol import CourseContract, validate_course_result
    from .deepagent_contract import request_snapshot, payload_digest

    (request, result), digest = _snapshot([request, result])
    request = request_snapshot(request)
    validate_course_result(result, request, CourseContract())
    values = {key: None for key in COURSE_TERMS}
    for item in result['explanations']:
        values[item['feature']] = item['contribution']
    blocked = result['status'] == 'BLOCKED'
    observations = {key: request[key] for key in
                    ('subjectCode', 'dataVersion', 'predictionWindowMonths', 'visits', 'features')}
    return {
        'schemaVersion': SCHEMA, 'mode': 'SYNTHETIC_DEMO',
        'subjectCode': request['subjectCode'], 'dataVersion': request['dataVersion'],
        'observationSha256': payload_digest(observations),
        'featureSchema': 'course-six-rule-terms-v1',
        'target': f"course-ranking-{request['predictionWindowMonths']}m",
        'outputSpace': 'rounded-rule-terms-before-final-clipping',
        'reference': 'fixed-base-0.18', 'unit': 'score',
        'modelVersion': result['modelVersion'],
        'methodVersion': 'graph-masked-synthetic-rule-v1', 'fold': 'NOT_APPLICABLE',
        'values': values,
        'evidence': {'kind': 'VALIDATED_COURSE_PAIR', 'sha256': digest},
        'missingReasons': {key: 'QUALITY_BLOCKED' if blocked else 'TERM_NOT_PRODUCED'
                           for key, number in values.items() if number is None},
    }


def _ranks(values):
    order = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        rank = (start + 1 + end) / 2
        for index in order[start:end]:
            ranks[index] = rank
        start = end
    return ranks


def _spearman(left, right):
    if len(left) < 2:
        return {'value': None, 'reason': 'INSUFFICIENT_SHARED_TERMS'}
    a, b = _ranks(left), _ranks(right)
    ca, cb = mean(a), mean(b)
    aa = sum((x - ca) ** 2 for x in a)
    bb = sum((x - cb) ** 2 for x in b)
    if not aa or not bb:
        return {'value': None, 'reason': 'CONSTANT_RANKS'}
    rho = sum((x - ca) * (y - cb) for x, y in zip(a, b)) / math.sqrt(aa * bb)
    return {'value': max(-1.0, min(1.0, rho)), 'reason': None}


def _top(values, k):
    if not values:
        return [], None
    cutoff = sorted((abs(x) for x in values.values()), reverse=True)[min(k, len(values)) - 1]
    return sorted(key for key, x in values.items() if abs(x) >= cutoff), cutoff


def _compare(left, right, k):
    _require(left['subjectCode'] == right['subjectCode'], 'SUBJECT_MISMATCH')
    _require(all(left[key] == right[key] for key in CONTEXT), 'CONTEXT_MISMATCH')
    a, b = left['values'], right['values']
    _require(set(a) == set(b), 'FEATURE_UNIVERSE_MISMATCH')
    _require(k <= len(a), 'TOP_K_RANGE')
    shared = sorted(key for key in a if a[key] is not None and b[key] is not None)
    av, bv = [a[key] for key in shared], [b[key] for key in shared]
    # Top sets use each arm's own available terms. Comparing only the
    # intersection here would hide the loss of an important missing feature.
    ta, ca = _top({key: x for key, x in a.items() if x is not None}, k)
    tb, cb = _top({key: x for key, x in b.items() if x is not None}, k)
    intersection, union = sorted(set(ta) & set(tb)), sorted(set(ta) | set(tb))
    jaccard = len(intersection) / len(union) if ta and tb else None
    sign = lambda x: (x > 0) - (x < 0)
    return {
        'subjectCode': left['subjectCode'], 'sharedTerms': shared,
        'comparisonContext': {key: left[key] for key in CONTEXT},
        'leftEvidence': copy.deepcopy(left['evidence']),
        'rightEvidence': copy.deepcopy(right['evidence']),
        'sharedTermCount': len(shared), 'featureCount': len(a),
        'missingLeft': copy.deepcopy(left['missingReasons']),
        'missingRight': copy.deepcopy(right['missingReasons']),
        'spearmanSigned': _spearman(av, bv),
        'spearmanMagnitude': _spearman([abs(x) for x in av], [abs(x) for x in bv]),
        'signChanges': [key for key in shared if sign(a[key]) != sign(b[key])],
        'topK': {'requestedK': k, 'tiePolicy': 'INCLUDE_ALL_AT_ABSOLUTE_CUTOFF',
                 'left': ta, 'right': tb, 'leftCutoff': ca, 'rightCutoff': cb,
                 'intersection': intersection, 'union': union,
                 'jaccard': jaccard, 'reason': None if jaccard is not None else 'EMPTY_ARM',
                 'fewerThanKLeft': sum(x is not None for x in a.values()) < k,
                 'fewerThanKRight': sum(x is not None for x in b.values()) < k},
    }


def compare_explanations(left, right, *, top_k=3):
    """Compare one declared synthetic pair; undefined correlations stay null."""
    _require(type(top_k) is int and 1 <= top_k <= 128, 'TOP_K_RANGE')
    (left, right), digest = _snapshot([left, right])
    result = _compare(_record(left), _record(right), top_k)
    return dict(result, comparisonVersion=COMPARISON_VERSION, inputSha256=digest, leftArm={key: left[key] for key in ARM},
                rightArm={key: right[key] for key in ARM}, **LIMITS)


def _percentile(values, fraction):
    values = sorted(values)
    position = fraction * (len(values) - 1)
    lo, hi = math.floor(position), math.ceil(position)
    return values[lo] + (values[hi] - values[lo]) * (position - lo)


def _summary(values, resamples, seed):
    if not values:
        return {'definedSubjects': 0, 'mean': None, 'interval95': None,
                'intervalReason': 'NO_DEFINED_SUBJECTS'}
    result = {'definedSubjects': len(values), 'mean': mean(values), 'interval95': None,
              'intervalReason': 'INSUFFICIENT_SUBJECTS'}
    if len(values) >= 2:
        rng = random.Random(seed)
        samples = [mean(rng.choices(values, k=len(values))) for _ in range(resamples)]
        result.update(interval95=[_percentile(samples, .025), _percentile(samples, .975)], intervalReason=None)
    return result


def compare_panels(left, right, *, top_k=3, resamples=1000, seed=0):
    """Pair unique subjects and bootstrap defined subject metrics, without fits.

    A panel is one fixed model/method/fold arm. Repeated folds for a subject
    must be compared separately, never counted as independent subjects.
    """
    _require(type(top_k) is int and 1 <= top_k <= 128, 'TOP_K_RANGE')
    _require(type(resamples) is int and 200 <= resamples <= 2000, 'RESAMPLE_RANGE')
    _require(type(seed) is int and 0 <= seed < 2**32, 'SEED_RANGE')
    _require(type(left) is list and type(right) is list
             and 1 <= len(left) <= 200 and 1 <= len(right) <= 200, 'PANEL_SIZE')
    (left, right), digest = _snapshot([left, right])
    panels = []
    for panel in (left, right):
        indexed = {}
        for value in panel:
            value = _record(value)
            subject = value['subjectCode']
            _require(subject not in indexed, 'DUPLICATE_SUBJECT')
            _require(all(value[key] == panel[0][key] for key in (*ARM, *CONTEXT)
                         if key != 'observationSha256'), 'MIXED_PANEL')
            _require(set(value['values']) == set(panel[0]['values']), 'MIXED_PANEL')
            _require(top_k <= len(value['values']), 'TOP_K_RANGE')
            indexed[subject] = value
        panels.append(indexed)
    a, b = panels
    shared = sorted(a.keys() & b.keys())
    # Reject incompatible arms even when the panels share no subjects.
    _require(all(left[0][key] == right[0][key] for key in CONTEXT
                 if key != 'observationSha256'), 'CONTEXT_MISMATCH')
    _require(set(left[0]['values']) == set(right[0]['values']), 'FEATURE_UNIVERSE_MISMATCH')
    pairs = [_compare(a[key], b[key], top_k) for key in shared]
    metrics = {
        'spearmanSigned': [row['spearmanSigned']['value'] for row in pairs],
        'spearmanMagnitude': [row['spearmanMagnitude']['value'] for row in pairs],
        'topKJaccard': [row['topK']['jaccard'] for row in pairs],
    }
    return {
        'comparisonVersion': COMPARISON_VERSION, 'topK': top_k,
        'inputSha256': digest, 'leftSubjects': len(left), 'rightSubjects': len(right),
        'pairedSubjects': len(pairs), 'leftOnly': sorted(a.keys() - b.keys()),
        'rightOnly': sorted(b.keys() - a.keys()), 'pairs': pairs,
        'leftArm': {key: left[0][key] for key in ARM},
        'rightArm': {key: right[0][key] for key in ARM},
        'summary': {key: dict(_summary([x for x in values if x is not None], resamples, seed),
                              undefinedSubjects=len(pairs) - sum(x is not None for x in values))
                    for key, values in metrics.items()},
        'uncertainty': {'method': 'SUBJECT_BOOTSTRAP_PERCENTILE_MEAN',
                        'resamples': resamples, 'seed': seed, 'level': .95,
                        'resamplingUnit': 'UNIQUE_PAIRED_SUBJECT',
                        'undefinedPolicy': 'EXCLUDE_AND_REPORT_PER_METRIC',
                        'populationInferenceEstablished': False,
                        'modelRefitted': False, 'interpretation': 'CONDITIONAL_SYNTHETIC_EMPIRICAL_ONLY'},
        **LIMITS,
    }
