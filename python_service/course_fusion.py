"""Shared temporal selection for already-validated original course requests.

No scoring, files, network or imputation. The workflow, preview and result
validator consume the same selection; this is not a new wire contract.
"""
from datetime import date
import hashlib
import json
import math

FEATURE_ORDER = ('APOE_E4_COUNT', 'MRI_HIPPOCAMPUS_L', 'MRI_HIPPOCAMPUS_R')
COGNITION = ('mmse', 'moca', 'cdrSb')
SIGNALS = (*COGNITION, *FEATURE_ORDER)
FEATURE_VERSION = 'course-longitudinal-features-v1'
MAX_MATRIX_INPUT = 1024 * 1024


def select_fusion(payload):
    """Select existing observations without mutating the validated request.

    Returned rows refer to the caller-owned request. Public entry points must
    validate/snapshot before calling; this internal helper never owns a model
    or silently repairs input. Later nulls do not erase earlier measurements.
    """
    visits = sorted(payload['visits'], key=lambda row: (row['visitDate'], row['visitCode']))
    latest = visits[-1] if visits else None
    cutoff = latest['visitDate'] if latest else None
    eligible = [row for row in payload['features'] if cutoff and row['recordedAt'] <= cutoff]
    selected, seen, conflict = {}, {}, False
    for row in sorted(eligible, key=lambda row: row['recordedAt']):
        key = (row['featureName'], row['recordedAt'])
        value = row.get('featureValue')
        conflict |= key in seen and seen[key] != value
        seen[key] = value
        if value is not None:
            selected[row['featureName']] = row
    has_cognition = latest is not None and any(latest.get(key) is not None for key in COGNITION)
    ambiguous = latest is not None and sum(row['visitDate'] == cutoff for row in visits) > 1
    unsupported = payload['predictionWindowMonths'] != 24
    missing = [name for name in FEATURE_ORDER if name not in selected]
    reasons = []
    if not has_cognition:
        reasons.append('CORE_COGNITION_MISSING')
    if ambiguous:
        reasons.append('AMBIGUOUS_INDEX_VISIT')
    if conflict:
        reasons.append('CONFLICTING_FEATURE_VALUES')
    if unsupported:
        reasons.append('UNSUPPORTED_WINDOW')
    excluded = len(payload['features']) - len(eligible)
    warnings = []
    if excluded:
        warnings.append('POST_INDEX_FEATURES_EXCLUDED')
    if missing:
        warnings.append('MISSING_MODALITIES')
    if latest and any(latest.get(key) is None for key in COGNITION):
        warnings.append('PARTIAL_COGNITION')
    return {'visits': visits, 'latest': latest, 'indexDate': cutoff,
            'eligibleFeatures': eligible, 'features': selected,
            'hasCognition': has_cognition, 'ambiguousIndex': ambiguous,
            'conflictingFeatures': conflict, 'unsupportedWindow': unsupported,
            'missingModalities': missing, 'excludedPostIndexFeatures': excluded,
            'blockingReasons': reasons, 'warningCodes': warnings, 'blocked': bool(reasons)}


class FusionError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def validate_fusion_selection(selection, payload):
    """Check a stage snapshot against the unchanged deterministic selection.

    This verifies tool consistency with supplied observations, not source
    authenticity, historical availability or a research baseline definition.
    """
    _require(type(selection) is dict, 'FUSION_SELECTION')
    _require(_input_digest(selection) == _input_digest(select_fusion(payload)), 'FUSION_SELECTION')
    return selection


def _require(condition, code):
    if not condition:
        raise FusionError(code)


def _input_digest(requests):
    """Bound encoded input before taking snapshots; errors never echo content."""
    digest, size = hashlib.sha256(), 0
    try:
        encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(',', ':'))
        for chunk in encoder.iterencode(requests):
            raw = chunk.encode('utf-8')
            size += len(raw)
            _require(size <= MAX_MATRIX_INPUT, 'FUSION_INPUT_SIZE')
            digest.update(raw)
    except FusionError:
        raise
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError, RuntimeError):
        raise FusionError('FUSION_INPUT_JSON') from None
    return digest.hexdigest()


def feature_dictionary():
    """Names, formulas and units for 26 descriptive columns; no model inputs."""
    formulas = {'firstObserved': 'y at earliest unique observed date in the declared window',
                'latestObserved': 'y at latest unique observed date in the declared window',
                'change': 'latestObserved - firstObserved',
                'endpointRatePerDay': '(latestObserved - firstObserved) / elapsed calendar days',
                'slopePerDay': 'sum((day-mean(day))*(y-mean(y))) / sum((day-mean(day))^2)'}
    dictionary = []
    for name in SIGNALS:
        unit = 'score' if name in COGNITION else 'count' if name == 'APOE_E4_COUNT' else 'normalized'
        modality = 'COGNITION' if name in COGNITION else 'GENETIC' if name == 'APOE_E4_COUNT' else 'MRI'
        statistics = ('latestObserved',) if modality == 'GENETIC' else tuple(formulas)
        for statistic in statistics:
            dictionary.append({'key': name + '.' + statistic, 'feature': name, 'statistic': statistic,
                               'modality': modality, 'unit': unit + ('/day' if statistic.endswith('PerDay') else ''),
                               'formula': formulas[statistic],
                               'minimumObservedDates': 1 if statistic in ('firstObserved', 'latestObserved') else 2,
                               'usesMinimumSpan': statistic.endswith('PerDay'),
                               'baselineMeaning': 'FIRST_OBSERVED_IN_WINDOW_NOT_STUDY_ENROLLMENT',
                               'usedByExistingScorer': False})
    return dictionary


def _signal_evidence(request, selected, name, lookback_days, min_span_days):
    index = date.fromisoformat(selected['indexDate']) if selected['indexDate'] else None
    start = date.fromordinal(max(1, index.toordinal() - lookback_days)) if index else None
    rows = []
    table = 'visits' if name in COGNITION else 'features'
    for position, row in enumerate(request[table], 1):
        if table == 'features' and row['featureName'] != name:
            continue
        field = name if table == 'visits' else 'featureValue'
        measured = date.fromisoformat(row['visitDate' if table == 'visits' else 'recordedAt'])
        source = {'table': table, 'recordIndex': position, 'field': field}
        if field not in row:
            source['fieldPresent'] = False
        rows.append((measured, row.get(field), source))
    included = [row for row in rows if index is not None and start <= row[0] <= index]
    groups = {}
    for measured, value, source in included:
        groups.setdefault(measured, []).append((value, source))
    points, duplicate_rows = [], 0
    for measured, group in sorted(groups.items()):
        values = {value for value, _ in group}
        # Different visit identities on one date are ambiguous even if their
        # current measurements happen to agree. Equal feature repeats collapse.
        ambiguous = len(group) > 1 if table == 'visits' else len(values) > 1
        if table == 'features' and not ambiguous:
            duplicate_rows += len(group) - 1
        value = None if ambiguous else group[0][0]
        points.append({'date': measured.isoformat(), 'value': value,
                       'state': 'AMBIGUOUS' if ambiguous else 'MISSING' if value is None else 'OBSERVED',
                       'sources': [source for _, source in group], 'availableDate': None})
    observed = [point for point in points if point['state'] == 'OBSERVED']
    ambiguous = any(point['state'] == 'AMBIGUOUS' for point in points)
    statistics = ('latestObserved',) if name == 'APOE_E4_COUNT' else (
        'firstObserved', 'latestObserved', 'change', 'endpointRatePerDay', 'slopePerDay')
    empty = 'NO_INDEX' if index is None else 'AMBIGUOUS' if ambiguous else 'MISSING'
    values = {statistic: None for statistic in statistics}
    states = {statistic: empty for statistic in statistics}
    elapsed = None
    if observed and not ambiguous:
        values['latestObserved'] = observed[-1]['value']
        states['latestObserved'] = 'OBSERVED'
        if name != 'APOE_E4_COUNT':
            values['firstObserved'] = observed[0]['value']
            states['firstObserved'] = 'OBSERVED'
            for statistic in ('change', 'endpointRatePerDay', 'slopePerDay'):
                states[statistic] = 'INSUFFICIENT_HISTORY'
            if len(observed) >= 2:
                days = [(date.fromisoformat(point['date']) - date.fromisoformat(observed[0]['date'])).days for point in observed]
                elapsed = days[-1]
                delta = float(observed[-1]['value']) - float(observed[0]['value'])
                values['change'], states['change'] = delta, 'OBSERVED'
                if elapsed >= min_span_days:
                    ys = [float(point['value']) for point in observed]
                    mean_x, mean_y = math.fsum(days) / len(days), math.fsum(ys) / len(ys)
                    denominator = math.fsum((day - mean_x) ** 2 for day in days)
                    values['endpointRatePerDay'] = delta / elapsed
                    values['slopePerDay'] = math.fsum((day - mean_x) * (y - mean_y) for day, y in zip(days, ys)) / denominator
                    states['endpointRatePerDay'] = states['slopePerDay'] = 'OBSERVED'
    current = (selected['latest'].get(name) if table == 'visits' and selected['latest'] else
               selected['features'].get(name, {}).get('featureValue'))
    evidence = {'windowStart': start.isoformat() if start else None, 'windowEnd': index.isoformat() if index else None,
                'totalRows': len(rows), 'includedRows': len(included), 'missingRows': sum(value is None for _, value, _ in included),
                'observedDates': len(observed), 'ambiguousDates': sum(point['state'] == 'AMBIGUOUS' for point in points),
                'equalFeatureRepeatRows': duplicate_rows,
                'beforeWindowRows': sum(measured < start for measured, _, _ in rows) if index else 0,
                'postIndexRows': sum(measured > index for measured, _, _ in rows) if index else 0,
                'unplacedRows': len(rows) if index is None else 0,
                'elapsedObservedDays': elapsed, 'points': points,
                'currentScoringValue': None if selected['blocked'] else current,
                'historicalAvailabilityVerified': False}
    return values, states, evidence


def build_fusion_matrix(requests, *, lookback_days=365, min_span_days=30):
    """Describe DEMO observations without scoring, model training or persistence.

    Lookback applies only to these descriptive columns. Original scoring still
    uses its original selection policy. The new columns are not automatically
    valid inputs to either the course scorer or the protected research models.
    """
    _require(type(lookback_days) is int and 1 <= lookback_days <= 3650 and
             type(min_span_days) is int and 1 <= min_span_days <= lookback_days, 'FUSION_WINDOW')
    _require(isinstance(requests, list) and 1 <= len(requests) <= 200, 'FUSION_REQUESTS')
    source_digest = _input_digest(requests)
    # Delayed import avoids a cycle: the original workflow imports select_fusion.
    from .deepagent_contract import request_snapshot, payload_digest, AgentContractError
    try:
        owned = [request_snapshot(request) for request in requests]
    except (AgentContractError, TypeError, KeyError, ValueError, RecursionError):
        raise FusionError('FUSION_REQUEST_INVALID') from None
    _require(_input_digest(owned) == source_digest, 'FUSION_INPUT_CHANGED')
    _require(len({row['subjectCode'] for row in owned}) == len(owned) and
             len({row['runId'] for row in owned}) == len(owned), 'FUSION_DUPLICATE_BINDING')
    _require(len({(row['dataVersion'], row['predictionWindowMonths']) for row in owned}) == 1, 'FUSION_MIXED_VERSIONS')
    dictionary = feature_dictionary()
    columns = [row['key'] for row in dictionary]
    rows = []
    for request in sorted(owned, key=lambda row: row['subjectCode']):
        selected = select_fusion(request)
        values, states, evidence = {}, {}, {}
        for name in SIGNALS:
            signal_values, signal_states, evidence[name] = _signal_evidence(request, selected, name, lookback_days, min_span_days)
            values.update({name + '.' + key: value for key, value in signal_values.items()})
            states.update({name + '.' + key: value for key, value in signal_states.items()})
        rows.append({'subjectCode': request['subjectCode'], 'runId': request['runId'], 'requestDigest': payload_digest(request),
                     'indexDate': selected['indexDate'], 'qualityStatus': 'BLOCKED' if selected['blocked'] else
                     'WARN' if selected['warningCodes'] else 'PASS', 'blockingReasons': selected['blockingReasons'],
                     'values': values, 'states': states, 'evidence': evidence,
                     'engineeringStatus': 'COMPLETE' if all(value is not None for value in values.values()) else 'PARTIAL',
                     'eligibleForExistingScoring': not selected['blocked'], 'riskScore': None})
    coverage = []
    for key in columns:
        states = [row['states'][key] for row in rows]
        count = sum(row['values'][key] is not None for row in rows)
        coverage.append({'key': key, 'observedSubjects': count, 'missingSubjects': len(rows) - count,
                         'observedFraction': count / len(rows), 'stateCounts': {state: states.count(state) for state in sorted(set(states))}})
    return {'scope': 'COURSE_SYNTHETIC_FEATURE_MATRIX', 'featureVersion': FEATURE_VERSION,
            'dataVersion': owned[0]['dataVersion'], 'requestModelVersion': owned[0]['modelVersion'],
            'predictionWindowMonths': owned[0]['predictionWindowMonths'], 'inputSha256': source_digest,
            'config': {'lookbackDays': lookback_days, 'minimumRateAndSlopeSpanDays': min_span_days,
                       'timeUnit': 'calendar_days', 'windowInclusive': True},
            'subjectCount': len(rows), 'columnOrder': columns, 'featureDictionary': dictionary, 'rows': rows,
            'missingMatrix': [[row['values'][key] is None for key in columns] for row in rows], 'coverage': coverage,
            'modelExecuted': False, 'modelFitted': False, 'imputedValues': 0, 'predictionProduced': False,
            'persisted': False, 'modelInputCompatible': False, 'sourceAuthenticityVerified': False,
            'historicalAvailabilityVerified': False, 'clinicalValidityAssessed': False,
            'limitations': ['First observation in this declared lookback is not a verified study-enrollment baseline.',
                            'Rates/slopes summarize observed points only; no interpolation, extrapolation or causal effect.',
                            'Typed-request record indices are not CSV physical lines or authenticated source identifiers.',
                            'These descriptive columns are not added to any existing model or wire response.']}
