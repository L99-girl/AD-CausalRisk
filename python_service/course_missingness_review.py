"""Compare complete validated original synthetic missingness scenario results.

No scoring or requests occur here. Score changes describe the fixed course
rules, not missing-modality clinical reliability, effects or model selection.
"""
from __future__ import annotations

from statistics import mean

from .course_missingness import _snapshot, _digest, _require, validate_missingness_plan
from .course_fusion import select_fusion
from .course_path_evidence import build_course_path_evidence

REVIEW_VERSION = 'course-missingness-review-v1'


def _source_use(scenario, result):
    path = build_course_path_evidence(scenario['request'], result)
    sources = {row['id']: row for row in path['sourceNodes']}
    uses = {}
    for term in path['termNodes']:
        refs = []
        for source_id in term['sourceIds']:
            source = sources[source_id]
            collection, index = source['collection'], source['recordIndex']
            ref = {'collection': collection, 'scenarioRecordIndex': index,
                   'baselineRecordIndex': scenario['sourceMap'][collection][index - 1],
                   'field': source['field'], 'observedAt': source['observedAt'],
                   'unit': source['unit'], 'availableAt': None}
            for key in ('featureName', 'visitCode'):
                if key in source:
                    ref[key] = source[key]
            refs.append(ref)
        uses[term['feature']] = {'sourceCount': len(refs), 'sources': refs[:20],
            'sourcesTruncated': len(refs) > 20, 'allSourceRefsSha256': _digest(refs, 1024 * 1024)}
    mri = uses.get('MRI_HIPPOCAMPUS', {}).get('sources', [])
    return uses, (mri[0]['featureName'] if mri else None), bool(path['contextOnlySources']), path


def _term_changes(baseline, result):
    a = {row['feature']: row for row in baseline['explanations']}
    b = {row['feature']: row for row in result['explanations']}
    return [{'feature': key, 'baselineContribution': a[key]['contribution'] if key in a else None,
             'scenarioContribution': b[key]['contribution'] if key in b else None,
             'delta': b[key]['contribution'] - a[key]['contribution'] if key in a and key in b else None,
             'presence': 'PRESENT_BOTH' if key in a and key in b else 'REMOVED' if key in a else 'ADDED',
             'directionChanged': a[key]['direction'] != b[key]['direction'] if key in a and key in b else None}
            for key in sorted(a.keys() | b.keys())]


def _summary(rows, mask, removed):
    matched = [row for row in rows if row['scoreDelta'] is not None]
    deltas = [row['scoreDelta'] for row in matched]
    return {'mask': mask, 'removedGroups': list(removed), 'subjects': len(rows),
        'baselineCompletedSubjects': sum(row['baselineStatus'] == 'COMPLETED' for row in rows),
        'scenarioCompletedSubjects': sum(row['status'] == 'COMPLETED' for row in rows),
        'comparableSubjects': len(matched),
        'newlyBlockedSubjects': sum(row['baselineStatus'] == 'COMPLETED' and row['status'] == 'BLOCKED' for row in rows),
        'unblockedDiagnosticSubjects': sum(row['baselineStatus'] == 'BLOCKED' and row['status'] == 'COMPLETED' for row in rows),
        'bothBlockedSubjects': sum(row['baselineStatus'] == row['status'] == 'BLOCKED' for row in rows),
        'positiveDeltaSubjects': sum(value > 0 for value in deltas),
        'negativeDeltaSubjects': sum(value < 0 for value in deltas), 'zeroDeltaSubjects': sum(value == 0 for value in deltas),
        'meanBaselineScoreOnComparableSubjects': mean(row['baselineScore'] for row in matched) if matched else None,
        'meanScenarioScoreOnComparableSubjects': mean(row['score'] for row in matched) if matched else None,
        'meanDelta': mean(deltas) if deltas else None, 'minimumDelta': min(deltas) if deltas else None,
        'maximumDelta': max(deltas) if deltas else None}


def review_missingness_results(plan, results):
    """Reject partial/bad input; compare only the complete verified result set."""
    from .course_protocol import CourseContract, validate_course_result

    plan, results = _snapshot([plan, results], 12 * 1024 * 1024)
    plan = validate_missingness_plan(plan)
    _require(type(results) is list and len(results) == plan['scenarioCount'], 'RESULT_COVERAGE')
    scenarios = {row['request']['runId']: row for row in plan['scenarios']}
    indexed = {}
    contract = CourseContract()
    for result in results:
        _require(type(result) is dict and type(result.get('runId')) is str, 'RESULT_IDENTITY')
        run_id = result['runId']
        _require(run_id in scenarios and run_id not in indexed, 'RESULT_IDENTITY')
        validate_course_result(result, scenarios[run_id]['request'], contract)
        indexed[run_id] = result
    _require(set(indexed) == set(scenarios), 'RESULT_COVERAGE')
    baselines = {row['subjectCode']: indexed[row['request']['runId']] for row in plan['scenarios'] if row['mask'] == 0}
    base_reasons = {row['subjectCode']: list(select_fusion(row)['blockingReasons']) for row in plan['baseRequests']}
    rows = []
    for scenario in plan['scenarios']:
        result = indexed[scenario['request']['runId']]
        baseline = baselines[scenario['subjectCode']]
        comparable = baseline['status'] == result['status'] == 'COMPLETED'
        use, mri, context_right, path = _source_use(scenario, result)
        rows.append({'subjectCode': scenario['subjectCode'], 'mask': scenario['mask'],
            'removedGroups': list(scenario['removedGroups']), 'runId': result['runId'],
            'originalRunId': scenario['baselineRunId'], 'baselineScenarioRunId': baseline['runId'],
            'requestSha256': scenario['requestSha256'], 'resultSha256': _digest(result, 256 * 1024),
            'inputChangedBeyondRunId': scenario['inputChangedBeyondRunId'],
            'baselineStatus': baseline['status'], 'status': result['status'],
            'baselineQualityStatus': baseline['qualityStatus'], 'qualityStatus': result['qualityStatus'],
            'qualityTransition': baseline['qualityStatus'] + '->' + result['qualityStatus'],
            'baselineScore': baseline['riskScore'], 'score': result['riskScore'],
            'scoreDelta': result['riskScore'] - baseline['riskScore'] if comparable else None,
            'riskLevelChanged': result['riskLevel'] != baseline['riskLevel'] if comparable else None,
            'originalBaselineBlockingReasons': list(base_reasons[scenario['subjectCode']]),
            'scenarioBlockingReasons': path['blockedReasons'],
            'nodeStates': {row['id']: row['status'] for row in result['graph']['nodes']},
            'termChanges': _term_changes(baseline, result), 'sourceUseByTerm': use,
            'usedMriFeature': mri, 'rightMriContextOnly': context_right,
            'clippingAdjustment': path['reconstruction']['clippingAdjustment'] if path['reconstruction'] else None,
            'clinicalReuseAuthorized': False, 'originalSourceProblemsAdjudicated': False})
    summary = []
    for mask in range(plan['maskCount']):
        group = [row for row in rows if row['mask'] == mask]
        summary.append(_summary(group, mask, group[0]['removedGroups']))
    return {'scope': 'COURSE_SYNTHETIC_MISSINGNESS_REVIEW', 'reviewVersion': REVIEW_VERSION,
        'planSha256': _digest(plan), 'suppliedResultsSha256': _digest(results, 8 * 1024 * 1024),
        'dataVersion': plan['dataVersion'], 'modelVersion': plan['modelVersion'],
        'predictionWindowMonths': plan['predictionWindowMonths'], 'granularity': plan['granularity'],
        'subjectCount': plan['subjectCount'], 'scenarioCount': plan['scenarioCount'],
        'baselineMask': 0, 'deltaDefinition': 'SCENARIO_MINUS_MATCHED_SUBJECT_BASELINE',
        'rows': rows, 'summary': summary, 'upstreamCourseResultsCompared': len(results),
        'scoringExecutedByThisCall': False, 'networkUsedByThisCall': False, 'upstreamExecutionVerified': False,
        'researchModelExecutedByThisCall': False, 'modelFitted': False, 'persisted': False,
        'alternativeModelSelected': False, 'clinicalConfidence': None,
        'clinicalReliabilityEstablished': False, 'causalEffectsIdentified': False,
        'limitations': [
            'Scores are original clipped additive course rankings, not calibrated probabilities.',
            'Erasure is a synthetic input stress test, not a biological intervention or missing-data mechanism.',
            'A source conflict disappearing after removal is diagnostic only; original reasons remain unresolved.',
            'Blocked scores/deltas and absent contributions remain null; summaries use matched nonblocked subjects.',
            'MRI fallback, protective terms and clipping can make sensitivity non-monotonic or hide lost contributions.',
            'Source refs map typed scenario arrays back to typed baseline arrays, not physical CSV lines.',
            'Content/schema checks do not certify execution, source authenticity, authorization or clinical validity.']}
