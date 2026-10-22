"""Explicit allocation, all-history removal, provenance and plan integrity."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from python_service.course_missingness import (
    MissingnessError, prepare_missingness_requests, validate_missingness_plan,
)
from python_service.course_protocol import CourseContract, validate_course_request

ROOT = Path(__file__).resolve().parents[1]


def request(subject='DEMO-001', run='run-base-001'):
    value = json.loads((ROOT / 'contracts/examples/deepagent-v1.request.example.json').read_text(encoding='utf-8'))
    value.update(subjectCode=subject, runId=run)
    return value


def ids(size, prefix='plan'):
    return [f'run-{prefix}-{i}' for i in range(size)]


def plan(body=None, granularity='MODALITY'):
    return prepare_missingness_requests([body or request()], ids(8 if granularity == 'MODALITY' else 64),
                                       granularity=granularity)


class MissingnessPlanTests(unittest.TestCase):
    def test_default_eight_masks_baseline_exact_except_run_id(self):
        body = request()
        value = plan(body)
        self.assertEqual(value['scenarioCount'], 8)
        self.assertEqual([row['mask'] for row in value['scenarios']], list(range(8)))
        baseline = value['scenarios'][0]
        expected = dict(body, runId='run-plan-0')
        self.assertEqual(baseline['request'], expected)
        self.assertEqual(baseline['removedGroups'], [])
        self.assertFalse(baseline['inputChangedBeyondRunId'])
        self.assertEqual(baseline['sourceMap'], {'visits': [1, 2], 'features': [1, 2, 3]})

    def test_cognition_all_history_erased_not_just_latest(self):
        value = plan()['scenarios'][1]
        self.assertEqual(value['removedGroups'], ['COGNITION'])
        for visit in value['request']['visits']:
            self.assertTrue(all(visit[field] is None for field in ('mmse', 'moca', 'cdrSb')))
        self.assertEqual(value['erasedCognitionValues'], {'cdrSb': 2, 'mmse': 2, 'moca': 2})
        self.assertEqual(value['request']['features'], request()['features'])

    def test_feature_removal_covers_older_duplicate_null_and_future_rows(self):
        body = request()
        body['features'].extend([dict(body['features'][0]),
            dict(body['features'][0], featureValue=None, recordedAt='2025-12-01'),
            dict(body['features'][0], featureValue=2, recordedAt='2026-02-01')])
        value = plan(body)['scenarios'][2]
        self.assertFalse(any(row['featureName'] == 'APOE_E4_COUNT' for row in value['request']['features']))
        self.assertEqual(value['removedFeatureRows'], 4)
        self.assertEqual(value['removedFeatureValues'], 3)
        self.assertEqual(value['sourceMap']['features'], [2, 3])

    def test_mri_modality_removes_both_sides_without_rewriting_other_fields(self):
        body = request()
        value = plan(body)['scenarios'][4]
        self.assertEqual(value['removedGroups'], ['MRI'])
        self.assertEqual(value['request']['features'], body['features'][:1])
        self.assertEqual(value['request']['visits'], body['visits'])
        for key in ('subjectCode', 'dataVersion', 'modelVersion', 'predictionWindowMonths', 'contractVersion'):
            self.assertEqual(value['request'][key], body[key])

    def test_signal_plan_64_masks_and_single_side_mri(self):
        value = plan(granularity='SIGNAL')
        self.assertEqual(value['maskCount'], 64)
        self.assertEqual(value['scenarios'][16]['removedGroups'], ['MRI_HIPPOCAMPUS_L'])
        self.assertEqual(value['scenarios'][16]['sourceMap']['features'], [1, 3])
        self.assertEqual(value['scenarios'][32]['sourceMap']['features'], [1, 2])
        self.assertTrue(all(visit['mmse'] is None for visit in value['scenarios'][1]['request']['visits']))
        self.assertEqual(value['scenarios'][1]['request']['visits'][0]['moca'], request()['visits'][0]['moca'])

    def test_already_missing_cells_do_not_get_fake_values_or_keys(self):
        body = request()
        body['features'] = []
        for visit in body['visits']:
            visit['mmse'] = None
            visit.pop('moca')
        value = plan(body)
        self.assertFalse(value['scenarios'][2]['inputChangedBeyondRunId'])
        self.assertFalse(value['scenarios'][4]['inputChangedBeyondRunId'])
        self.assertNotIn('moca', value['scenarios'][1]['request']['visits'][0])
        self.assertEqual(value['scenarios'][1]['erasedCognitionValues']['mmse'], 0)

    def test_zero_values_are_erased_and_counted_as_observed(self):
        body = request()
        for row in body['visits']:
            row['mmse'] = 0
        body['features'][0]['featureValue'] = 0
        value = plan(body)
        self.assertEqual(value['scenarios'][1]['erasedCognitionValues']['mmse'], 2)
        self.assertEqual(value['scenarios'][2]['removedFeatureValues'], 1)

    def test_subject_sorting_and_explicit_run_id_mapping(self):
        a, z = request('DEMO-A', 'run-base-a'), request('DEMO-Z', 'run-base-z')
        value = prepare_missingness_requests([z, a], ids(16))
        self.assertEqual(value['scenarios'][0]['subjectCode'], 'DEMO-A')
        self.assertEqual(value['scenarios'][8]['subjectCode'], 'DEMO-Z')
        self.assertEqual(value['scenarios'][8]['request']['runId'], 'run-plan-8')

    def test_100_original_subjects_800_valid_original_requests(self):
        rows = json.loads((ROOT / 'fixtures/synthetic_subjects_100.json').read_text(encoding='utf-8'))['subjects']
        value = prepare_missingness_requests(rows, ids(800, 'cohort'))
        self.assertEqual((value['subjectCount'], value['scenarioCount']), (100, 800))
        contract = CourseContract()
        for scenario in value['scenarios']:
            validate_course_request(scenario['request'], contract)
        self.assertEqual(validate_missingness_plan(value), value)

    def test_inputs_scenarios_and_base_snapshots_are_detached_without_execution(self):
        body, allocations = request(), ids(8)
        before = copy.deepcopy([body, allocations])
        with patch('python_service.deepagent_contract.run_workflow', side_effect=AssertionError('no execution')):
            value = prepare_missingness_requests([body], allocations)
        value['scenarios'][0]['request']['visits'][0]['mmse'] = 1
        self.assertEqual([body, allocations], before)
        self.assertEqual(value['baseRequests'][0]['visits'][0]['mmse'], 28)
        self.assertEqual(value['scenarios'][2]['request']['visits'][0]['mmse'], 28)
        self.assertFalse(value['scoringExecutedByThisCall'])
        self.assertIsNone(value['clinicalConfidence'])

    def test_allocations_must_be_exact_unique_valid_and_not_reused(self):
        for allocations in (ids(7), ids(9), ['run-same'] * 8, ids(7) + ['invalid'],
                            ids(7) + ['run-base-001'], ids(7) + [True], tuple(ids(8))):
            with self.assertRaises(MissingnessError):
                prepare_missingness_requests([request()], allocations)

    def test_duplicate_base_subject_or_run_id_rejected(self):
        a = request()
        for b in (request('DEMO-001', 'run-other'), request('DEMO-002', 'run-base-001')):
            with self.assertRaisesRegex(MissingnessError, 'DUPLICATE_BASE_BINDING'):
                prepare_missingness_requests([a, b], ids(16))

    def test_mixed_versions_windows_and_private_or_invalid_request_rejected(self):
        for field, content in (('dataVersion', 'demo-other'), ('predictionWindowMonths', 12)):
            with self.assertRaisesRegex(MissingnessError, 'MIXED_BASE'):
                prepare_missingness_requests([request(), dict(request('DEMO-002', 'run-other'), **{field: content})], ids(16))
        for field, content in (('subjectCode', 'PRIVATE-001'), ('modelVersion', 'other'), ('predictionWindowMonths', True)):
            with self.assertRaises(MissingnessError):
                prepare_missingness_requests([dict(request(), **{field: content})], ids(8))

    def test_invalid_granularity_counts_unicode_and_size_rejected(self):
        for mode in ('unknown', True, None):
            with self.assertRaises(MissingnessError):
                plan(granularity=mode)
        with self.assertRaises(MissingnessError):
            prepare_missingness_requests([], [])
        with self.assertRaises(MissingnessError):
            prepare_missingness_requests([request()] * 101, ids(808))
        for value in ('\ud800', 'x' * (1024 * 1024)):
            with self.assertRaises(MissingnessError):
                prepare_missingness_requests([dict(request(), dataVersion=value)], ids(8))

    def test_more_than_1000_signal_scenarios_rejected_before_generation(self):
        bodies = [request(f'DEMO-{i}', f'run-base-{i}') for i in range(16)]
        with self.assertRaisesRegex(MissingnessError, 'SCENARIO_COUNT_LIMIT'):
            prepare_missingness_requests(bodies, ids(1024), granularity='SIGNAL')

    def test_request_expansion_is_bounded_before_all_scenarios_allocated(self):
        bodies = [request(f'DEMO-{i}', f'run-base-{i}') for i in range(3)]
        for body in bodies:
            body['features'] = [dict(body['features'][0]) for _ in range(500)]
        with self.assertRaisesRegex(MissingnessError, 'SCENARIO_BYTES_LIMIT'):
            prepare_missingness_requests(bodies, ids(192), granularity='SIGNAL')

    def test_plan_changes_in_masks_maps_requests_hashes_flags_or_metadata_rejected(self):
        original = plan()
        for mode in ('mask', 'map', 'body', 'hash', 'flag', 'extra', 'boolean-mask'):
            value = copy.deepcopy(original)
            if mode == 'mask':
                value['scenarios'][1]['removedGroups'] = []
            elif mode == 'map':
                value['scenarios'][2]['sourceMap']['features'][0] = 1
            elif mode == 'body':
                value['scenarios'][1]['request']['visits'][0]['mmse'] = 28
            elif mode == 'hash':
                value['scenarios'][0]['requestSha256'] = 'a' * 64
            elif mode == 'flag':
                value['scoringExecutedByThisCall'] = True
            elif mode == 'extra':
                value['extra'] = True
            else:
                value['scenarios'][1]['mask'] = True
            with self.subTest(mode=mode), self.assertRaisesRegex(MissingnessError, 'PLAN_RECONSTRUCTION_MISMATCH'):
                validate_missingness_plan(value)

    def test_window_and_existing_conflict_not_silently_repaired_in_plan(self):
        body = request()
        body['predictionWindowMonths'] = 12
        body['features'].append(dict(body['features'][0], featureValue=2))
        value = plan(body)
        self.assertTrue(all(row['request']['predictionWindowMonths'] == 12 for row in value['scenarios']))
        self.assertEqual(value['scenarios'][0]['request']['features'], body['features'])


if __name__ == '__main__':
    unittest.main()
