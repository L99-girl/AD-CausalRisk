"""Constructed decision curves and paired subject bootstrap, without fitting."""
from __future__ import annotations

from bisect import bisect_left
import math
import random
from statistics import mean

from .prediction_evaluation import (
    _checked, _snapshot, _protocol, _panel, _digest, _scope, _limits,
    _rank_metrics, _require,
)

VERSION = 'synthetic-paired-prediction-comparison-v1'
METRICS = ('rocAuc', 'averagePrecision', 'prAucTrapezoidal', 'brier')


def _benefits(rows, thresholds):
    ordered = sorted(rows, key=lambda row: row['probability'])
    scores = [row['probability'] for row in ordered]
    positives = [0]
    for row in ordered:
        positives.append(positives[-1] + row['outcome'])
    size = len(rows)
    values = []
    for threshold in thresholds:
        index = bisect_left(scores, threshold)
        tp = positives[-1] - positives[index]
        fp = size - index - tp
        odds = threshold / (1 - threshold)
        values.append({'threshold': threshold, 'tp': tp, 'fp': fp,
            'falsePositiveWeight': odds, 'modelNetBenefit': tp / size - fp / size * odds,
            'treatAllNetBenefit': positives[-1] / size - (size - positives[-1]) / size * odds,
            'treatNoneNetBenefit': 0.})
    return values


def decision_curve(protocol, panel):
    """Apply only predeclared thresholds to complete constructed binary data."""
    protocol, panel, rows = _checked(protocol, panel)
    return {'scope': 'CONSTRUCTED_DECISION_CURVE', 'comparisonVersion': VERSION,
            'protocolSha256': _digest(protocol), 'panelSha256': _digest(panel),
            'modelVersion': panel['modelVersion'], 'context': _scope(protocol),
            'subjects': len(rows), 'eventCount': sum(row['outcome'] for row in rows),
            'classificationRule': 'PROBABILITY_GREATER_THAN_OR_EQUAL_TO_THRESHOLD',
            'curves': _benefits(rows, protocol['thresholds']),
            'clinicalThresholdRecommendation': None, 'clinicalUtilityEstablished': False, **_limits()}


def _scalars(rows):
    return dict(_rank_metrics(rows), brier=mean((row['probability'] - row['outcome']) ** 2 for row in rows))


def _difference(left, right):
    return right - left if left is not None and right is not None else None


def _percentile(ordered, probability):
    position = probability * (len(ordered) - 1)
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _interval(observed, samples, subjects):
    defined = sorted(value for value in samples if value is not None)
    reason = 'OBSERVED_METRIC_UNDEFINED' if observed is None else (
             'INSUFFICIENT_SUBJECTS' if subjects < 2 else (
             'INSUFFICIENT_DEFINED_REPLICATES' if len(defined) < 2 else None))
    return {'observedDifference': observed, 'definedReplicates': len(defined),
            'undefinedReplicates': len(samples) - len(defined),
            'interval95': None if reason else [_percentile(defined, .025), _percentile(defined, .975)],
            'intervalReason': reason}


def compare_prediction_panels(protocol, left, right, *, resamples=1000, seed=0):
    """Bootstrap paired unique subjects; retain invalid class-resample counts.

    Predictions are fixed: no training, CV repetition, calibration fitting,
    threshold search, automatic redraw or hypothesis test occurs.
    """
    _require(type(resamples) is int and 200 <= resamples <= 2000, 'RESAMPLE_RANGE')
    _require(type(seed) is int and 0 <= seed < 2**32, 'SEED_RANGE')
    protocol, left, right = _snapshot([protocol, left, right])
    protocol = _protocol(protocol)
    a, b = _panel(protocol, left), _panel(protocol, right)
    _require(all(x['subjectCode'] == y['subjectCode'] and x['outcome'] == y['outcome']
                 and x['foldId'] == y['foldId'] for x, y in zip(a, b)), 'PAIRED_OUTCOME_MISMATCH')
    left_values, right_values = _scalars(a), _scalars(b)
    thresholds = protocol['thresholds']
    left_curve, right_curve = _benefits(a, thresholds), _benefits(b, thresholds)
    metric_samples = {key: [] for key in METRICS}
    benefit_samples = [[] for _ in thresholds]
    rng, size = random.Random(seed), len(a)
    for _ in range(resamples):
        indices = rng.choices(range(size), k=size)
        aa, bb = [a[index] for index in indices], [b[index] for index in indices]
        ma, mb = _scalars(aa), _scalars(bb)
        for key in METRICS:
            metric_samples[key].append(_difference(ma[key], mb[key]))
        for samples, ca, cb in zip(benefit_samples, _benefits(aa, thresholds), _benefits(bb, thresholds)):
            samples.append(cb['modelNetBenefit'] - ca['modelNetBenefit'])
    return {'scope': 'CONSTRUCTED_PAIRED_MODEL_COMPARISON', 'comparisonVersion': VERSION,
            'protocolSha256': _digest(protocol), 'leftPanelSha256': _digest(left), 'rightPanelSha256': _digest(right),
            'leftModelVersion': left['modelVersion'], 'rightModelVersion': right['modelVersion'],
            'context': _scope(protocol), 'pairedSubjects': size,
            'pairedSubjectCodes': [row['subjectCode'] for row in a], 'differenceDefinition': 'RIGHT_MINUS_LEFT',
            'leftMetrics': left_values, 'rightMetrics': right_values,
            'metricDifferences': {key: _interval(_difference(left_values[key], right_values[key]), metric_samples[key], size)
                                  for key in METRICS},
            'decisionCurveDifferences': [dict(_interval(cb['modelNetBenefit'] - ca['modelNetBenefit'], samples, size),
                threshold=threshold, leftNetBenefit=ca['modelNetBenefit'], rightNetBenefit=cb['modelNetBenefit'])
                for threshold, ca, cb, samples in zip(thresholds, left_curve, right_curve, benefit_samples)],
            'uncertainty': {'method': 'PAIRED_SUBJECT_BOOTSTRAP_PERCENTILE', 'resamples': resamples,
                'seed': seed, 'level': .95, 'resamplingUnit': 'UNIQUE_SUBJECT',
                'undefinedPolicy': 'EXCLUDE_PER_METRIC_AND_REPORT_WITHOUT_REDRAW',
                'intervalsAreSimultaneous': False, 'modelRefitted': False, 'populationInferenceEstablished': False,
                'interpretation': 'CONDITIONAL_CONSTRUCTED_FIXED_PREDICTIONS_ONLY'},
            'clinicalThresholdRecommendation': None, 'clinicalUtilityEstablished': False, **_limits()}
