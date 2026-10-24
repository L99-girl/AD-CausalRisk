"""Reconstruct validated synthetic rule paths from exact typed input records.

This is provenance for an existing result, not another prediction or causal
mediation graph. Raw rule arithmetic is reused from the frozen result checker.
"""
from __future__ import annotations

from .course_graph import _snapshot, _digest, inspect_course_graph
from .course_fusion import select_fusion

PATH_VERSION = 'course-rule-path-evidence-v1'
TERM_FORMULAS = (
    ('MMSE', 'clip((27 - latest.mmse) / 10, -0.08, 0.22)'),
    ('MoCA', 'clip((25 - latest.moca) / 12, -0.04, 0.14)'),
    ('CDR_SB', 'clip(latest.cdrSb / 10, 0, 0.20)'),
    ('MMSE_DELTA', 'clip(-(latest.mmse - first.mmse) / 30, -0.08, 0.14)'),
    ('APOE_E4_COUNT', 'clip(latestNonNullAPOE * 0.045, 0, 0.09)'),
    ('MRI_HIPPOCAMPUS', 'clip((0.42 - leftIfAvailableElseRight) * 0.22, -0.03, 0.07)'),
)
COGNITIVE_FIELDS = {'MMSE': 'mmse', 'MoCA': 'moca', 'CDR_SB': 'cdrSb'}


def _visit_source(request, visit, field):
    index = next(index for index, row in enumerate(request['visits']) if row['visitCode'] == visit['visitCode'])
    return {'id': f'visits:{index + 1}:{field}', 'collection': 'visits', 'recordIndex': index + 1,
            'field': field, 'jsonPointer': f'/visits/{index}/{field}',
            'visitCode': visit['visitCode'], 'value': visit[field], 'unit': 'score',
            'observedAt': visit['visitDate'], 'availableAt': None,
            'evidenceLevel': 'DECLARED_SYNTHETIC_OBSERVATION'}


def _feature_sources(request, observation):
    return [{'id': f'features:{index + 1}:featureValue', 'collection': 'features',
             'recordIndex': index + 1, 'field': 'featureValue', 'jsonPointer': f'/features/{index}/featureValue',
             'featureName': row['featureName'], 'value': row['featureValue'], 'unit': row['unit'],
             'observedAt': row['recordedAt'], 'availableAt': None,
             'evidenceLevel': 'DECLARED_SYNTHETIC_OBSERVATION'}
            for index, row in enumerate(request['features'])
            if all(row.get(key) == observation[key] for key in ('featureName', 'featureValue', 'recordedAt', 'unit'))]


def _term_sources(request, selected, term):
    visits, latest, features = selected['visits'], selected['latest'], selected['features']
    if term in COGNITIVE_FIELDS:
        return [_visit_source(request, latest, COGNITIVE_FIELDS[term])]
    if term == 'MMSE_DELTA':
        return [_visit_source(request, visits[0], 'mmse'), _visit_source(request, latest, 'mmse')]
    if term == 'APOE_E4_COUNT':
        return _feature_sources(request, features['APOE_E4_COUNT'])
    side = 'MRI_HIPPOCAMPUS_L' if 'MRI_HIPPOCAMPUS_L' in features else 'MRI_HIPPOCAMPUS_R'
    return _feature_sources(request, features[side])


def _missing_reason(term, selected):
    if selected['blocked']:
        return 'QUALITY_BLOCKED'
    if term in COGNITIVE_FIELDS:
        return 'INDEX_COGNITION_MISSING'
    if term == 'MMSE_DELTA':
        if len(selected['visits']) < 2:
            return 'INSUFFICIENT_VISITS'
        if selected['visits'][0].get('mmse') is None:
            return 'FIRST_OBSERVED_MMSE_MISSING'
        return 'INDEX_MMSE_MISSING'
    return 'NO_ELIGIBLE_APOE_OBSERVATION' if term == 'APOE_E4_COUNT' else 'NO_ELIGIBLE_MRI_OBSERVATION'


def build_course_path_evidence(request, result):
    """Trace a verified AgentResult; never invoke a scorer, model or network.

    Sources refer to the supplied typed arrays (one-based recordIndex, zero-
    based JSON Pointer), not CSV physical lines or authenticated clinical files.
    """
    from .deepagent_contract import request_snapshot, payload_digest
    from .course_protocol import CourseContract, validate_course_result, _rule_terms

    request, result = _snapshot([request, result], 512 * 1024)
    request = request_snapshot(request)
    validate_course_result(result, request, CourseContract())
    selected = select_fusion(request)
    inspection = inspect_course_graph(request)
    blocked = selected['blocked']
    sources, terms, edges, paths = {}, [], [], []
    raw_terms = {} if blocked else _rule_terms(selected['visits'], selected['latest'], selected['features'])[0]
    formulas = dict(TERM_FORMULAS)
    for index, explanation in enumerate(result['explanations']):
        name = explanation['feature']
        references = _term_sources(request, selected, name)
        for reference in references:
            sources[reference['id']] = reference
        term_id = 'term:' + name
        source_ids = [reference['id'] for reference in references]
        terms.append({'id': term_id, 'feature': name, 'formula': formulas[name],
                      'rawContribution': raw_terms[name], 'contribution': explanation['contribution'],
                      'contributionUnit': 'score', 'direction': explanation['direction'],
                      'evidenceLevel': explanation['evidenceLevel'], 'interpretation': explanation['interpretation'],
                      'sourceIds': source_ids, 'resultExplanationIndex': index + 1,
                      'duplicateSourcePolicy': 'ALL_MATCHING_REFERENCES_ONE_RULE_TERM'})
        edges.extend({'from': source, 'to': term_id, 'kind': 'DERIVED_FROM', 'weight': None,
                      'evidenceLevel': 'RULE_PROVENANCE'} for source in source_ids)
        edges.append({'from': term_id, 'to': 'output:course-score', 'kind': 'ADDITIVE_TERM',
                      'weight': explanation['contribution'], 'weightUnit': 'score',
                      'evidenceLevel': 'PREDICTIVE_DEMO', 'weightMeaning': 'ROUNDED_RULE_CONTRIBUTION'})
        paths.append({'sourceIds': source_ids, 'termId': term_id, 'targetId': 'output:course-score',
                      'weight': explanation['contribution'], 'weightUnit': 'score',
                      'direction': explanation['direction'], 'evidenceLevel': 'PREDICTIVE_DEMO',
                      'causalInterpretationAllowed': False})
    context = []
    if not blocked and {'MRI_HIPPOCAMPUS_L', 'MRI_HIPPOCAMPUS_R'} <= selected['features'].keys():
        context = _feature_sources(request, selected['features']['MRI_HIPPOCAMPUS_R'])
    reconstruction = None
    output = None
    if not blocked:
        before = .18
        for raw in raw_terms.values():
            before += raw
        after = max(.05, min(.95, before))
        wire_sum = sum(row['contribution'] for row in result['explanations'])
        wire_reconstructed = max(.05, min(.95, .18 + wire_sum))
        reconstruction = {'base': .18, 'termOrder': list(raw_terms),
                          'unroundedScoreBeforeClipping': before, 'clippingBounds': [.05, .95],
                          'clippingAdjustment': after - before, 'unroundedScoreAfterClipping': after,
                          'finalRoundingAdjustment': result['riskScore'] - after,
                          'returnedScore': result['riskScore'], 'roundedTermsSum': wire_sum,
                          'roundedTermsClippedReconstruction': wire_reconstructed,
                          'wireRoundingResidual': result['riskScore'] - wire_reconstructed,
                          'maximumWireRoundingDifference': (len(terms) + 1) * .00005 + 1e-12,
                          'algebraMatchesValidatedScore': round(after, 4) == result['riskScore'],
                          'notAnIndependentPrediction': True}
        output = {'id': 'output:course-score', 'value': result['riskScore'], 'unit': 'score',
                  'evidenceLevel': 'PREDICTIVE_DEMO', 'meaning': 'EXISTING_VALIDATED_RESULT'}
    return {'scope': 'COURSE_SYNTHETIC_RULE_PATH_EVIDENCE', 'pathVersion': PATH_VERSION,
            'subjectCode': request['subjectCode'], 'runId': request['runId'],
            'dataVersion': request['dataVersion'], 'modelVersion': result['modelVersion'],
            'workflowVersion': result['workflowVersion'], 'contractVersion': result['contractVersion'],
            'requestSha256': payload_digest(request), 'resultSha256': _digest(result, 256 * 1024),
            'templateVersion': inspection['template']['templateVersion'], 'templateSha256': inspection['templateSha256'],
            'indexDate': selected['indexDate'], 'upstreamStatus': result['status'],
            'upstreamQualityStatus': result['qualityStatus'], 'upstreamResultScore': result['riskScore'],
            'eligibilityGraph': inspection['graph'], 'sourceNodes': list(sources.values()),
            'termNodes': terms, 'outputNode': output, 'edges': edges, 'paths': paths,
            'contextOnlySources': context, 'reconstruction': reconstruction,
            'missingTerms': {name: _missing_reason(name, selected) for name, _ in TERM_FORMULAS if name not in raw_terms},
            'blockedReasons': list(selected['blockingReasons']),
            'modelExecuted': False, 'modelFitted': False, 'predictionProduced': False, 'persisted': False,
            'sourceAuthenticityVerified': False, 'historicalAvailabilityVerified': False,
            'edgeStabilityEstablished': False, 'causalEffectsIdentified': False, 'clinicalValidityAssessed': False,
            'limitations': [*result['limitations'],
                'Record indices refer to supplied typed arrays; JSON Pointers use zero-based indices.',
                'Dates are declared observation dates; historical availability remains unknown.',
                'Rule edges describe arithmetic provenance, not biological mediation or learned causal effects.',
                'First MMSE uses the original full supplied visit history, not the descriptive matrix lookback.',
                'Context-only right MRI does not add a second contribution when left MRI is available.']}
