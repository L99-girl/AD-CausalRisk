"""Bounded synthetic binary evaluation with declared subject split checks.

Only caller-constructed probabilities/complete labels are accepted. This does
not execute, fit, recalibrate or certify a model, endpoint or OOF membership.
"""
from __future__ import annotations

from bisect import bisect_left
import copy
import hashlib
import json
import math
import re
from statistics import mean

PROTOCOL_SCHEMA = 'synthetic-binary-evaluation-v1'
PANEL_SCHEMA = 'constructed-probability-panel-v1'
VERSION = 'synthetic-binary-metrics-v1'
PROTOCOL_KEYS = {'schemaVersion', 'mode', 'protocolVersion', 'dataVersion', 'endpointId',
                 'horizonMonths', 'labelPolicy', 'splitType', 'evaluationSubjects', 'splits',
                 'thresholds', 'calibrationBinEdges'}
LIMITATIONS = (
    'Constructed synthetic complete binary outcomes only; no censoring or competing-event estimator.',
    'Declared subject splits do not certify training identity, temporal availability or OOF predictions.',
    'Course additive ranking scores are not calibrated probabilities and are not adapted here.',
    'Calibration bins are descriptive; no calibration intercept/slope or recalibration is fitted.',
    'These arithmetic checks do not establish research acceptance, clinical precision or utility.',
)


class EvaluationError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _require(condition, code):
    if not condition:
        raise EvaluationError(code)


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _digest(value):
    size, digest = 0, hashlib.sha256()
    try:
        encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        for chunk in encoder.iterencode(value):
            raw = chunk.encode('utf-8')
            size += len(raw)
            _require(size <= 1024 * 1024, 'EVALUATION_INPUT_SIZE')
            digest.update(raw)
        return digest.hexdigest()
    except EvaluationError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise EvaluationError('EVALUATION_JSON_INPUT') from None


def _snapshot(value):
    digest = _digest(value)
    try:
        owned = copy.deepcopy(value)
    except (ValueError, TypeError, RecursionError):
        raise EvaluationError('EVALUATION_JSON_INPUT') from None
    _require(_digest(owned) == digest, 'EVALUATION_INPUT_CHANGED')
    return owned


def _demo_version(value):
    return type(value) is str and re.fullmatch(r'demo-[A-Za-z0-9][A-Za-z0-9-]{0,94}', value) is not None


def _subjects(values, maximum):
    _require(type(values) is list and 1 <= len(values) <= maximum, 'SUBJECT_LIST')
    _require(all(type(value) is str and re.fullmatch(r'DEMO-[A-Za-z0-9-]{1,45}', value) for value in values),
             'SYNTHETIC_SUBJECT_ONLY')
    _require(len(set(values)) == len(values), 'DUPLICATE_SUBJECT')
    return set(values)


def _protocol(protocol):
    _require(type(protocol) is dict and set(protocol) == PROTOCOL_KEYS, 'PROTOCOL_FIELDS')
    _require(protocol['schemaVersion'] == PROTOCOL_SCHEMA and protocol['mode'] == 'SYNTHETIC_TEST', 'SYNTHETIC_SCOPE')
    _require(all(_demo_version(protocol[key]) for key in ('protocolVersion', 'dataVersion', 'endpointId')), 'DEMO_VERSION')
    _require(type(protocol['horizonMonths']) is int and protocol['horizonMonths'] == 24
             and protocol['labelPolicy'] == 'CONSTRUCTED_COMPLETE_BINARY_NO_CENSORING', 'ENDPOINT_SCOPE')
    _require(protocol['splitType'] in ('HOLDOUT', 'OOF'), 'SPLIT_TYPE')
    population = _subjects(protocol['evaluationSubjects'], 200)
    splits = protocol['splits']
    _require(type(splits) is list and 1 <= len(splits) <= 20, 'SPLIT_COUNT')
    _require(protocol['splitType'] != 'HOLDOUT' or len(splits) == 1, 'HOLDOUT_SPLITS')
    _require(protocol['splitType'] != 'OOF' or len(splits) >= 2, 'OOF_SPLITS')
    seen_folds, tested = set(), set()
    for split in splits:
        _require(type(split) is dict and set(split) == {'foldId', 'trainSubjects', 'testSubjects'}, 'SPLIT_FIELDS')
        fold = split['foldId']
        _require(_demo_version(fold) and fold not in seen_folds, 'FOLD_ID')
        seen_folds.add(fold)
        train, test = _subjects(split['trainSubjects'], 1000), _subjects(split['testSubjects'], 200)
        _require(not train & test, 'TRAIN_TEST_SUBJECT_LEAKAGE')
        _require(test <= population and not tested & test, 'TEST_SUBJECT_ASSIGNMENT')
        tested |= test
    _require(tested == population, 'EVALUATION_SUBJECT_COVERAGE')
    thresholds, edges = protocol['thresholds'], protocol['calibrationBinEdges']
    _require(type(thresholds) is list and 1 <= len(thresholds) <= 50
             and all(_number(x) and 0 < x < 1 for x in thresholds), 'THRESHOLDS')
    _require(all(a < b for a, b in zip(thresholds, thresholds[1:])), 'THRESHOLD_ORDER')
    _require(type(edges) is list and 2 <= len(edges) <= 21 and all(_number(x) for x in edges)
             and edges[0] == 0 and edges[-1] == 1
             and all(a < b for a, b in zip(edges, edges[1:])), 'CALIBRATION_BINS')
    return protocol


def validate_evaluation_protocol(protocol):
    """Check declared unique subject groups, not actual training provenance."""
    return _protocol(_snapshot(protocol))


def protocol_sha256(protocol):
    return _digest(validate_evaluation_protocol(protocol))


def _panel(protocol, panel):
    _require(type(panel) is dict and set(panel) == {'schemaVersion', 'mode', 'protocolSha256',
             'modelVersion', 'source', 'predictions'}, 'PANEL_FIELDS')
    _require(panel['schemaVersion'] == PANEL_SCHEMA and panel['mode'] == 'SYNTHETIC_TEST'
             and panel['source'] == 'CONSTRUCTED_TEST_VECTOR', 'CONSTRUCTED_PROBABILITIES_ONLY')
    _require(panel['protocolSha256'] == _digest(protocol), 'PROTOCOL_BINDING')
    _require(_demo_version(panel['modelVersion']), 'DEMO_MODEL_VERSION')
    predictions = panel['predictions']
    _require(type(predictions) is list and 1 <= len(predictions) <= 200, 'PANEL_SIZE')
    folds = {subject: split['foldId'] for split in protocol['splits'] for subject in split['testSubjects']}
    seen = set()
    for row in predictions:
        _require(type(row) is dict and set(row) == {'subjectCode', 'foldId', 'outcome', 'probability'}, 'PREDICTION_FIELDS')
        subject = row['subjectCode']
        _require(type(subject) is str and subject in folds and subject not in seen, 'PREDICTION_SUBJECT')
        _require(row['foldId'] == folds[subject], 'PREDICTION_FOLD')
        _require(type(row['outcome']) is int and row['outcome'] in (0, 1), 'COMPLETE_BINARY_OUTCOME')
        _require(_number(row['probability']) and 0 <= row['probability'] <= 1, 'PROBABILITY_RANGE')
        seen.add(subject)
    _require(seen == set(folds), 'PREDICTION_COVERAGE')
    return sorted(predictions, key=lambda row: row['subjectCode'])


def _checked(protocol, panel):
    protocol, panel = _snapshot([protocol, panel])
    return _protocol(protocol), panel, _panel(protocol, panel)


def _ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def _rank_metrics(rows):
    positives = sum(row['outcome'] for row in rows)
    negatives = len(rows) - positives
    groups = {}
    for row in rows:
        group = groups.setdefault(row['probability'], [0, 0])
        group[row['outcome']] += 1
    below_negatives, concordant = 0, 0.
    for score in sorted(groups):
        neg, pos = groups[score]
        concordant += pos * (below_negatives + neg / 2)
        below_negatives += neg
    ap, pr_trap, tp, fp, last_recall, last_precision = 0., 0., 0, 0, 0., 1.
    for score in sorted(groups, reverse=True):
        neg, pos = groups[score]
        tp += pos
        fp += neg
        recall = tp / positives if positives else 0.
        precision = tp / (tp + fp)
        ap += (recall - last_recall) * precision
        pr_trap += (recall - last_recall) * (precision + last_precision) / 2
        last_recall, last_precision = recall, precision
    return {'rocAuc': _ratio(concordant, positives * negatives),
            'averagePrecision': ap if positives else None,
            'prAucTrapezoidal': pr_trap if positives else None}


def _confusion(rows, threshold):
    tp = sum(row['outcome'] == 1 and row['probability'] >= threshold for row in rows)
    fp = sum(row['outcome'] == 0 and row['probability'] >= threshold for row in rows)
    fn = sum(row['outcome'] == 1 and row['probability'] < threshold for row in rows)
    tn = len(rows) - tp - fp - fn
    return {'threshold': threshold, 'tp': tp, 'fp': fp, 'tn': tn, 'fn': fn,
            'sensitivity': _ratio(tp, tp + fn), 'specificity': _ratio(tn, tn + fp),
            'positivePredictiveValue': _ratio(tp, tp + fp), 'negativePredictiveValue': _ratio(tn, tn + fn)}


def _metrics(rows, edges, thresholds):
    ranks = _rank_metrics(rows)
    brier = mean((row['probability'] - row['outcome']) ** 2 for row in rows)
    bins = [[] for _ in range(len(edges) - 1)]
    for row in rows:
        bins[bisect_left(edges[1:-1], row['probability'])].append(row)
    calibration = []
    for index, members in enumerate(bins):
        calibration.append({'lower': edges[index], 'upper': edges[index + 1], 'count': len(members),
            'eventCount': sum(row['outcome'] for row in members),
            'meanProbability': mean(row['probability'] for row in members) if members else None,
            'eventFraction': mean(row['outcome'] for row in members) if members else None})
    event_fraction = mean(row['outcome'] for row in rows)
    mean_probability = mean(row['probability'] for row in rows)
    return {'subjects': len(rows), 'eventCount': sum(row['outcome'] for row in rows),
            'nonEventCount': sum(1 - row['outcome'] for row in rows), 'eventFraction': event_fraction,
            **ranks, 'brier': brier,
            'undefinedMetrics': {key: 'BOTH_CLASSES_REQUIRED' if key == 'rocAuc' else 'NO_POSITIVE_OUTCOMES'
                                 for key, value in ranks.items() if value is None},
            'classificationRule': 'PROBABILITY_GREATER_THAN_OR_EQUAL_TO_THRESHOLD',
            'classification': [_confusion(rows, threshold) for threshold in thresholds],
            'calibration': {'bins': calibration, 'binPolicy': 'RIGHT_CLOSED_FIRST_INCLUDES_ZERO',
                'meanProbability': mean_probability, 'predictedMinusObserved': mean_probability - event_fraction,
                'expectedCalibrationError': sum(row['count'] * abs(row['meanProbability'] - row['eventFraction'])
                    for row in calibration if row['count']) / len(rows),
                'fittedIntercept': None, 'fittedSlope': None, 'fitReason': 'NOT_FITTED'}}


def _scope(protocol):
    return {'protocolVersion': protocol['protocolVersion'], 'dataVersion': protocol['dataVersion'],
            'endpointId': protocol['endpointId'], 'horizonMonths': protocol['horizonMonths'],
            'labelPolicy': protocol['labelPolicy'], 'splitType': protocol['splitType'],
            'splitSummary': [{'foldId': split['foldId'], 'trainSubjects': len(split['trainSubjects']),
                              'testSubjects': len(split['testSubjects'])} for split in protocol['splits']],
            'declaredSubjectDisjointnessChecked': True, 'actualTrainingMembershipVerified': False,
            'temporalAvailabilityVerified': False, 'outOfFoldPredictionsVerified': False}


def _limits():
    return {'modelExecuted': False, 'modelFitted': False, 'predictionProduced': False,
            'recalibrated': False, 'persisted': False, 'sourceAuthenticityVerified': False,
            'researchAcceptanceEstablished': False, 'clinicalValidityEstablished': False,
            'limitations': list(LIMITATIONS)}


def evaluate_predictions(protocol, panel):
    """Describe supplied constructed probabilities under one declared protocol."""
    protocol, panel, rows = _checked(protocol, panel)
    return {'scope': 'CONSTRUCTED_BINARY_EVALUATION', 'evaluationVersion': VERSION,
            'protocolSha256': _digest(protocol), 'panelSha256': _digest(panel),
            'modelVersion': panel['modelVersion'], 'context': _scope(protocol),
            'metrics': _metrics(rows, protocol['calibrationBinEdges'], protocol['thresholds']),
            'foldMetrics': {split['foldId']: _metrics([row for row in rows if row['foldId'] == split['foldId']],
                            protocol['calibrationBinEdges'], protocol['thresholds']) for split in protocol['splits']},
            **_limits()}
