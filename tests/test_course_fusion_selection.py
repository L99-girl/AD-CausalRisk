"""Shared fusion selection preserves the current four-stage input policy."""
import copy
import itertools
import json
from pathlib import Path
import unittest
from python_service.course_fusion import select_fusion
from python_service.course_csv import quality_summary
from python_service.course_protocol import context
from python_service.deepagent_contract import run_workflow
from python_service.demo_scoring import score_java_synthetic_payload

ROOT = Path(__file__).resolve().parents[1]


def request():
    return json.loads((ROOT / 'contracts/examples/deepagent-v1.request.example.json').read_text(encoding='utf-8'))


class SelectionTests(unittest.TestCase):
    def assert_consistent(self, body):
        before = copy.deepcopy(body)
        selected = select_fusion(body)
        preview = quality_summary(body)
        value = run_workflow(body, score_java_synthetic_payload)
        self.assertEqual(context(body), tuple(selected[key] for key in
                         ('visits', 'latest', 'indexDate', 'features', 'eligibleFeatures', 'blocked')))
        self.assertEqual(value['qualityStatus'], preview['qualityStatus'])
        self.assertEqual(selected['blocked'], value['status'] == 'BLOCKED')
        self.assertEqual(value['stages'][0]['summary']['featureCount'], len(selected['features']))
        self.assertEqual(value['stages'][0]['summary']['excludedPostIndexFeatures'], selected['excludedPostIndexFeatures'])
        self.assertEqual(preview['blockingReasons'], selected['blockingReasons'])
        self.assertEqual(preview['warningCodes'], selected['warningCodes'])
        self.assertEqual(body, before)
        return selected

    def test_all_100_original_profiles_agree_across_three_consumers(self):
        rows = json.loads((ROOT / 'fixtures/synthetic_subjects_100.json').read_text(encoding='utf-8'))['subjects']
        for body in rows:
            self.assert_consistent(body)

    def test_64_cognition_and_modality_missing_combinations(self):
        for cognition, modalities in itertools.product(range(8), range(8)):
            body = request()
            for bit, field in enumerate(('mmse', 'moca', 'cdrSb')):
                if cognition & (1 << bit):
                    body['visits'][-1][field] = None
            body['features'] = [row for bit, row in enumerate(body['features']) if not modalities & (1 << bit)]
            self.assert_consistent(body)

    def test_later_null_retains_previous_non_null_feature(self):
        body = request()
        body['features'].append(dict(body['features'][0], featureValue=None, recordedAt='2025-12-01'))
        selected = self.assert_consistent(body)
        self.assertEqual(selected['features']['APOE_E4_COUNT']['featureValue'], 1)
        self.assertEqual(selected['features']['APOE_E4_COUNT']['recordedAt'], '2025-01-01')

    def test_zero_is_an_observation_and_is_not_a_missing_modality(self):
        body = request()
        body['features'][0]['featureValue'] = 0
        body['features'][1]['featureValue'] = 0
        body['visits'][-1].update(mmse=0, moca=0, cdrSb=0)
        selected = self.assert_consistent(body)
        self.assertFalse(selected['blocked'])
        self.assertEqual(selected['missingModalities'], [])

    def test_post_index_features_do_not_override_eligible_values(self):
        body = request()
        body['features'].append(dict(body['features'][0], featureValue=2, recordedAt='2026-02-01'))
        selected = self.assert_consistent(body)
        self.assertEqual(selected['excludedPostIndexFeatures'], 1)
        self.assertEqual(selected['features']['APOE_E4_COUNT']['featureValue'], 1)

    def test_same_date_equal_duplicates_are_collapsed_without_blocking(self):
        body = request()
        body['features'].append(dict(body['features'][0]))
        selected = self.assert_consistent(body)
        self.assertEqual(len(selected['features']), 3)
        self.assertEqual(len(selected['eligibleFeatures']), 4)
        self.assertFalse(selected['conflictingFeatures'])

    def test_null_and_nonnull_same_date_are_conflicting(self):
        body = request()
        body['features'].append(dict(body['features'][0], featureValue=None))
        selected = self.assert_consistent(body)
        self.assertIn('CONFLICTING_FEATURE_VALUES', selected['blockingReasons'])

    def test_multiple_latest_visits_do_not_select_an_unambiguous_index(self):
        body = request()
        body['visits'].append(dict(body['visits'][-1], visitCode='OTHER'))
        selected = self.assert_consistent(body)
        self.assertTrue(selected['ambiguousIndex'])

    def test_no_visit_means_no_invented_index_or_feature_date_anchor(self):
        body = request()
        body['visits'] = []
        selected = self.assert_consistent(body)
        self.assertIsNone(selected['indexDate'])
        self.assertEqual(selected['features'], {})
        self.assertEqual(selected['excludedPostIndexFeatures'], 3)

    def test_latest_cognition_is_not_backfilled_from_earlier_visits(self):
        body = request()
        body['visits'][-1].update(mmse=None, moca=None, cdrSb=None)
        selected = self.assert_consistent(body)
        self.assertFalse(selected['hasCognition'])
        self.assertIn('CORE_COGNITION_MISSING', selected['blockingReasons'])

    def test_other_valid_window_is_blocked_without_changing_selection(self):
        body = request()
        body['predictionWindowMonths'] = 12
        selected = self.assert_consistent(body)
        self.assertEqual(selected['blockingReasons'], ['UNSUPPORTED_WINDOW'])
        self.assertEqual(len(selected['features']), 3)

    def test_unsorted_visits_and_features_keep_original_chronology(self):
        body = request()
        body['visits'].reverse()
        body['features'].reverse()
        selected = self.assert_consistent(body)
        self.assertEqual(selected['visits'][0]['visitCode'], 'BL')
        self.assertEqual(selected['latest']['visitCode'], 'M12')


if __name__ == '__main__':
    unittest.main()
