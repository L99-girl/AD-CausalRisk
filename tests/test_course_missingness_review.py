"""Missingness comparisons must retain gates, sources and matched denominators."""
import copy
import unittest
from unittest.mock import patch

from python_service.course_missingness import MissingnessError, prepare_missingness_requests
from python_service.course_missingness_review import review_missingness_results
from python_service.deepagent_contract import run_workflow
from python_service.demo_scoring import score_java_synthetic_payload
from python_service.course_protocol import CourseProtocolError
from test_course_missingness import request, ids, plan


def results(value):
    return [run_workflow(row['request'], score_java_synthetic_payload) for row in value['scenarios']]


def review(body=None, granularity='MODALITY'):
    value = plan(body, granularity)
    return review_missingness_results(value, results(value))


def change(row, feature):
    return next(value for value in row['termChanges'] if value['feature'] == feature)


class MissingnessReviewTests(unittest.TestCase):
    def test_hand_computed_modality_scores_and_blocked_nulls(self):
        value = review()
        baseline, cognition, genetics, _, mri, _, both, _ = value['rows']
        self.assertEqual(baseline['score'], .8304)
        self.assertAlmostEqual(genetics['scoreDelta'], -.045)
        self.assertAlmostEqual(mri['scoreDelta'], -.0154)
        self.assertAlmostEqual(both['scoreDelta'], -.0604)
        self.assertEqual(cognition['status'], 'BLOCKED')
        self.assertIsNone(cognition['score'])
        self.assertIsNone(cognition['scoreDelta'])
        self.assertIsNone(cognition['riskLevelChanged'])
        self.assertEqual(cognition['sourceUseByTerm'], {})
        self.assertEqual(value['summary'][1]['comparableSubjects'], 0)
        self.assertIsNone(value['summary'][1]['meanDelta'])

    def test_all_64_signals_have_expected_56_completed_8_blocked(self):
        value = review(granularity='SIGNAL')
        self.assertEqual(len(value['rows']), 64)
        self.assertEqual(sum(row['status'] == 'COMPLETED' for row in value['rows']), 56)
        self.assertEqual(sum(row['status'] == 'BLOCKED' for row in value['rows']), 8)
        self.assertTrue(all(row['scoreDelta'] is None for row in value['rows'] if row['status'] == 'BLOCKED'))

    def test_absent_terms_remain_null_and_presence_removed(self):
        row = review()['rows'][2]
        value = change(row, 'APOE_E4_COUNT')
        self.assertEqual(value['baselineContribution'], .045)
        self.assertIsNone(value['scenarioContribution'])
        self.assertIsNone(value['delta'])
        self.assertEqual(value['presence'], 'REMOVED')

    def test_present_zero_contribution_stays_observed(self):
        body = request()
        body['features'][0]['featureValue'] = 0
        value = change(review(body)['rows'][0], 'APOE_E4_COUNT')
        self.assertEqual(value['baselineContribution'], 0)
        self.assertEqual(value['scenarioContribution'], 0)
        self.assertEqual(value['delta'], 0)
        self.assertEqual(value['presence'], 'PRESENT_BOTH')

    def test_actual_mri_fallback_and_reindexed_source_map(self):
        value = review(granularity='SIGNAL')
        base, left_removed, right_removed = value['rows'][0], value['rows'][16], value['rows'][32]
        self.assertEqual(base['usedMriFeature'], 'MRI_HIPPOCAMPUS_L')
        self.assertTrue(base['rightMriContextOnly'])
        self.assertEqual(left_removed['usedMriFeature'], 'MRI_HIPPOCAMPUS_R')
        self.assertAlmostEqual(left_removed['scoreDelta'], -.0022)
        ref = left_removed['sourceUseByTerm']['MRI_HIPPOCAMPUS']['sources'][0]
        self.assertEqual((ref['scenarioRecordIndex'], ref['baselineRecordIndex']), (2, 3))
        self.assertEqual(right_removed['scoreDelta'], 0)
        self.assertEqual(right_removed['usedMriFeature'], 'MRI_HIPPOCAMPUS_L')
        self.assertEqual(right_removed['qualityTransition'], 'PASS->WARN')
        self.assertFalse(right_removed['rightMriContextOnly'])

    def test_whole_genetics_removal_maps_left_mri_back_to_original_second_row(self):
        row = review()['rows'][2]
        source = row['sourceUseByTerm']['MRI_HIPPOCAMPUS']['sources'][0]
        self.assertEqual((source['scenarioRecordIndex'], source['baselineRecordIndex']), (1, 2))
        self.assertEqual(source['featureName'], 'MRI_HIPPOCAMPUS_L')
        self.assertIsNone(source['availableAt'])

    def test_removing_protective_mri_can_increase_score(self):
        body = request()
        for feature in body['features'][1:]:
            feature['featureValue'] = 1
        value = review(body)
        self.assertAlmostEqual(value['rows'][4]['scoreDelta'], .03)
        self.assertEqual(value['summary'][4]['positiveDeltaSubjects'], 1)
        self.assertFalse(value['causalEffectsIdentified'])

    def test_upper_clipping_can_hide_missing_contribution(self):
        body = request()
        body['visits'][0]['mmse'] = 30
        body['visits'][-1].update(mmse=0, moca=0, cdrSb=18)
        for feature in body['features']:
            feature['featureValue'] = 2 if feature['featureName'] == 'APOE_E4_COUNT' else 0
        value = review(body)
        self.assertEqual(value['rows'][0]['score'], .95)
        self.assertEqual(value['rows'][2]['score'], .95)
        self.assertEqual(value['rows'][2]['scoreDelta'], 0)
        self.assertEqual(change(value['rows'][2], 'APOE_E4_COUNT')['presence'], 'REMOVED')
        self.assertLess(value['rows'][0]['clippingAdjustment'], 0)

    def test_lower_clipping_delta_not_equal_to_removed_term(self):
        body = request()
        for visit in body['visits']:
            visit.update(mmse=30, moca=30, cdrSb=0)
        for feature in body['features']:
            feature['featureValue'] = 0 if feature['featureName'] == 'APOE_E4_COUNT' else 1
        value = review(body)
        self.assertEqual(value['rows'][0]['score'], .05)
        self.assertAlmostEqual(value['rows'][4]['scoreDelta'], .01)
        self.assertEqual(change(value['rows'][4], 'MRI_HIPPOCAMPUS')['baselineContribution'], -.03)

    def test_conflict_removed_is_diagnostic_and_keeps_original_block_reason(self):
        body = request()
        body['features'].append(dict(body['features'][0], featureValue=2))
        value = review(body)
        row = value['rows'][2]
        self.assertEqual((row['baselineStatus'], row['status']), ('BLOCKED', 'COMPLETED'))
        self.assertIn('CONFLICTING_FEATURE_VALUES', row['originalBaselineBlockingReasons'])
        self.assertIsNone(row['scoreDelta'])
        self.assertFalse(row['originalSourceProblemsAdjudicated'])
        self.assertFalse(row['clinicalReuseAuthorized'])
        self.assertEqual(value['summary'][2]['unblockedDiagnosticSubjects'], 1)
        self.assertEqual(value['summary'][2]['comparableSubjects'], 0)

    def test_summaries_use_matched_subjects_not_changed_completed_cohort(self):
        a, b = request('DEMO-A', 'run-base-a'), request('DEMO-B', 'run-base-b')
        b['features'].append(dict(b['features'][0], featureValue=2))
        p = prepare_missingness_requests([a, b], ids(16))
        value = review_missingness_results(p, results(p))
        summary = value['summary'][2]
        self.assertEqual((summary['subjects'], summary['baselineCompletedSubjects'], summary['scenarioCompletedSubjects']), (2, 1, 2))
        self.assertEqual(summary['comparableSubjects'], 1)
        expected = next(row['score'] for row in value['rows'] if row['subjectCode'] == 'DEMO-A' and row['mask'] == 2)
        self.assertEqual(summary['meanScenarioScoreOnComparableSubjects'], expected)

    def test_unsupported_window_stays_blocked_everywhere(self):
        value = review(dict(request(), predictionWindowMonths=12))
        for row in value['rows']:
            self.assertEqual(row['status'], 'BLOCKED')
            self.assertIsNone(row['score'])
            self.assertIsNone(row['scoreDelta'])
            self.assertIn('UNSUPPORTED_WINDOW', row['originalBaselineBlockingReasons'])
        self.assertTrue(all(summary['bothBlockedSubjects'] == 1 for summary in value['summary']))

    def test_already_missing_inputs_and_unused_old_mmse_not_backfilled(self):
        body = request()
        body['features'] = []
        value = review(body)
        for index in (2, 4, 6):
            self.assertFalse(value['rows'][index]['inputChangedBeyondRunId'])
            self.assertEqual(value['rows'][index]['scoreDelta'], 0)
        body = request()
        body['visits'][-1]['mmse'] = None
        value = review(body, granularity='SIGNAL')
        self.assertNotIn('MMSE', value['rows'][0]['sourceUseByTerm'])
        self.assertNotIn('MMSE_DELTA', value['rows'][0]['sourceUseByTerm'])
        self.assertTrue(value['rows'][1]['inputChangedBeyondRunId'])
        self.assertEqual(value['rows'][1]['scoreDelta'], 0)

    def test_result_order_does_not_change_rows_or_summaries(self):
        p = plan()
        values = results(p)
        a = review_missingness_results(p, values)
        b = review_missingness_results(p, list(reversed(values)))
        self.assertEqual(a['rows'], b['rows'])
        self.assertEqual(a['summary'], b['summary'])
        self.assertNotEqual(a['suppliedResultsSha256'], b['suppliedResultsSha256'])

    def test_truncated_duplicate_source_refs_keep_full_count_and_digest(self):
        body = request()
        body['features'].extend([dict(body['features'][1]) for _ in range(30)])
        value = review(body)['rows'][0]['sourceUseByTerm']['MRI_HIPPOCAMPUS']
        self.assertEqual(value['sourceCount'], 31)
        self.assertEqual(len(value['sources']), 20)
        self.assertTrue(value['sourcesTruncated'])
        self.assertEqual(len(value['allSourceRefsSha256']), 64)

    def test_partial_duplicate_extra_wrong_or_non_list_results_rejected(self):
        p = plan()
        values = results(p)
        for supplied in (values[:-1], values + [values[0]], [values[0]] * 8, tuple(values), None,
                         [dict(values[0], runId='run-unknown')] + values[1:]):
            with self.assertRaises(MissingnessError):
                review_missingness_results(p, supplied)

    def test_wire_valid_tampering_rejected_before_a_report(self):
        p = plan()
        for mode in ('score', 'term', 'blocked', 'version'):
            values = results(p)
            if mode == 'score':
                values[0]['riskScore'] = .5
            elif mode == 'term':
                values[0]['explanations'][0]['contribution'] += .01
            elif mode == 'blocked':
                values[1]['riskScore'] = 0
            else:
                values[0]['dataVersion'] = 'demo-other'
            with self.subTest(mode=mode), self.assertRaises(CourseProtocolError):
                review_missingness_results(p, values)

    def test_source_map_or_mask_tampering_fails_before_source_lookup(self):
        p = plan()
        values = results(p)
        p['scenarios'][2]['sourceMap']['features'][0] = 999
        with self.assertRaisesRegex(MissingnessError, 'PLAN_RECONSTRUCTION_MISMATCH'):
            review_missingness_results(p, values)

    def test_no_scoring_no_aliases_and_confidence_remains_unknown(self):
        p = plan()
        values = results(p)
        before = copy.deepcopy([p, values])
        with patch('python_service.deepagent_contract.run_workflow', side_effect=AssertionError('no scoring')):
            value = review_missingness_results(p, values)
        value['rows'][0]['originalBaselineBlockingReasons'].append('edited')
        self.assertEqual([p, values], before)
        self.assertFalse(value['scoringExecutedByThisCall'])
        self.assertFalse(value['upstreamExecutionVerified'])
        self.assertFalse(value['alternativeModelSelected'])
        self.assertIsNone(value['clinicalConfidence'])
        self.assertFalse(value['clinicalReliabilityEstablished'])


if __name__ == '__main__':
    unittest.main()
