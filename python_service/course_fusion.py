"""Shared temporal selection for already-validated original course requests.

No scoring, files, network or imputation. The workflow, preview and result
validator consume the same selection; this is not a new wire contract.
"""

FEATURE_ORDER = ('APOE_E4_COUNT', 'MRI_HIPPOCAMPUS_L', 'MRI_HIPPOCAMPUS_R')
COGNITION = ('mmse', 'moca', 'cdrSb')


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
        conflict |= key in seen and seen[key] != row['featureValue']
        seen[key] = row['featureValue']
        if row['featureValue'] is not None:
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
