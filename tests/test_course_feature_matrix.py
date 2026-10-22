"""Descriptive longitudinal features, provenance and missingness; no models."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from python_service.course_fusion import build_fusion_matrix, feature_dictionary, FusionError
from python_service.deepagent_contract import payload_digest, request_snapshot

ROOT = Path(__file__).resolve().parents[1]


def request():
    return json.loads((ROOT / 'contracts/examples/deepagent-v1.request.example.json').read_text(encoding='utf-8'))


def matrix(body=None, **config):
    return build_fusion_matrix([body or request()], **config)


class FeatureMatrixTests(unittest.TestCase):
    def test_26_dictionary_columns_have_formulas_units_and_no_implicit_model_use(self):
        value = matrix()
        self.assertEqual(len(value['columnOrder']), 26)
        self.assertEqual(value['columnOrder'], [row['key'] for row in feature_dictionary()])
        for column in value['featureDictionary']:
            self.assertTrue(column['formula'])
            self.assertIn(column['unit'], ('score', 'score/day', 'normalized', 'normalized/day', 'count'))
            self.assertFalse(column['usedByExistingScorer'])
        json.dumps(value, allow_nan=False)

    def test_two_observed_visits_use_actual_calendar_days(self):
        value = matrix()['rows'][0]['values']
        self.assertEqual(value['mmse.firstObserved'], 28)
        self.assertEqual(value['mmse.latestObserved'], 25)
        self.assertEqual(value['mmse.change'], -3)
        self.assertAlmostEqual(value['mmse.endpointRatePerDay'], -3 / 365)
        self.assertAlmostEqual(value['mmse.slopePerDay'], -3 / 365)

    def test_ols_over_all_observed_dates_is_distinct_from_endpoint_rate(self):
        body = request()
        body['visits'] = [dict(body['visits'][-1], visitCode=code, visitDate=day, mmse=y)
                          for code, day, y in [('A', '2025-01-01', 0), ('B', '2025-01-11', 10), ('C', '2025-01-31', 10)]]
        value = matrix(body)['rows'][0]
        self.assertAlmostEqual(value['values']['mmse.endpointRatePerDay'], 1 / 3)
        self.assertAlmostEqual(value['values']['mmse.slopePerDay'], 2 / 7)
        self.assertEqual([p['date'] for p in value['evidence']['mmse']['points']], ['2025-01-01', '2025-01-11', '2025-01-31'])

    def test_short_history_has_observed_change_but_no_rate_or_slope(self):
        body = request()
        body['visits'][0]['visitDate'] = '2025-12-30'
        row = matrix(body)['rows'][0]
        self.assertEqual(row['values']['mmse.change'], -3)
        self.assertIsNone(row['values']['mmse.slopePerDay'])
        self.assertEqual(row['states']['mmse.endpointRatePerDay'], 'INSUFFICIENT_HISTORY')

    def test_single_mri_observation_does_not_create_zero_change_or_slope(self):
        row = matrix()['rows'][0]
        self.assertEqual(row['values']['MRI_HIPPOCAMPUS_L.latestObserved'], .35)
        for stat in ('change', 'endpointRatePerDay', 'slopePerDay'):
            self.assertIsNone(row['values']['MRI_HIPPOCAMPUS_L.' + stat])
            self.assertEqual(row['states']['MRI_HIPPOCAMPUS_L.' + stat], 'INSUFFICIENT_HISTORY')

    def test_lookback_is_inclusive_and_does_not_redefine_original_scoring(self):
        row = matrix(lookback_days=30)['rows'][0]
        self.assertEqual(row['values']['mmse.firstObserved'], 25)
        self.assertIsNone(row['values']['mmse.change'])
        self.assertEqual(row['evidence']['mmse']['beforeWindowRows'], 1)
        self.assertIsNone(row['values']['APOE_E4_COUNT.latestObserved'])
        self.assertEqual(row['evidence']['APOE_E4_COUNT']['currentScoringValue'], 1)

    def test_late_null_does_not_erase_latest_observed_feature(self):
        body = request()
        body['features'].append(dict(body['features'][1], featureValue=None, recordedAt='2025-12-01'))
        row = matrix(body)['rows'][0]
        self.assertEqual(row['values']['MRI_HIPPOCAMPUS_L.latestObserved'], .35)
        self.assertEqual(row['evidence']['MRI_HIPPOCAMPUS_L']['missingRows'], 1)
        self.assertEqual(len(row['evidence']['MRI_HIPPOCAMPUS_L']['points']), 2)

    def test_latest_observed_cognition_is_not_a_backfill_for_current_scoring(self):
        body = request()
        body['visits'][-1]['mmse'] = None
        row = matrix(body)['rows'][0]
        self.assertEqual(row['values']['mmse.latestObserved'], 28)
        self.assertIsNone(row['evidence']['mmse']['currentScoringValue'])
        self.assertEqual(row['qualityStatus'], 'WARN')

    def test_zero_remains_observed_in_values_and_missing_matrix(self):
        body = request()
        body['visits'][-1]['mmse'] = 0
        body['features'][0]['featureValue'] = 0
        value = matrix(body)
        for key in ('mmse.latestObserved', 'APOE_E4_COUNT.latestObserved'):
            self.assertEqual(value['rows'][0]['values'][key], 0)
            self.assertFalse(value['missingMatrix'][0][value['columnOrder'].index(key)])

    def test_equal_feature_repeats_preserve_both_sources_but_one_observation(self):
        body = request()
        body['features'].append(dict(body['features'][1]))
        row = matrix(body)['rows'][0]
        evidence = row['evidence']['MRI_HIPPOCAMPUS_L']
        self.assertEqual(evidence['observedDates'], 1)
        self.assertEqual(evidence['equalFeatureRepeatRows'], 1)
        self.assertEqual([ref['recordIndex'] for ref in evidence['points'][0]['sources']], [2, 4])
        self.assertIsNone(row['values']['MRI_HIPPOCAMPUS_L.slopePerDay'])

    def test_conflicting_same_day_values_are_not_averaged(self):
        for other in (None, .8):
            body = request()
            body['features'].append(dict(body['features'][1], featureValue=other))
            row = matrix(body)['rows'][0]
            self.assertEqual(row['states']['MRI_HIPPOCAMPUS_L.latestObserved'], 'AMBIGUOUS')
            self.assertIsNone(row['values']['MRI_HIPPOCAMPUS_L.firstObserved'])
            self.assertEqual(row['qualityStatus'], 'BLOCKED')
            self.assertIsNone(row['riskScore'])

    def test_same_day_visit_identities_are_ambiguous_even_with_equal_values(self):
        body = request()
        body['visits'].append(dict(body['visits'][0], visitCode='OTHER-BASELINE'))
        row = matrix(body)['rows'][0]
        self.assertEqual(row['states']['mmse.slopePerDay'], 'AMBIGUOUS')
        self.assertEqual(row['evidence']['mmse']['ambiguousDates'], 1)
        self.assertEqual(row['qualityStatus'], 'PASS')  # Existing scorer's latest visit is unique.
        self.assertEqual(row['evidence']['mmse']['currentScoringValue'], 25)

    def test_missing_middle_point_is_retained_without_interpolation(self):
        body = request()
        body['visits'].append(dict(body['visits'][0], visitCode='GAP', visitDate='2025-06-01', mmse=None))
        evidence = matrix(body)['rows'][0]['evidence']['mmse']
        self.assertEqual(evidence['includedRows'], 3)
        self.assertEqual(evidence['observedDates'], 2)
        self.assertEqual(evidence['points'][1]['state'], 'MISSING')
        self.assertIsNone(evidence['points'][1]['value'])

    def test_post_index_features_are_counted_and_never_used(self):
        body = request()
        body['features'].append(dict(body['features'][1], featureValue=.99, recordedAt='2026-02-01'))
        row = matrix(body)['rows'][0]
        self.assertEqual(row['values']['MRI_HIPPOCAMPUS_L.latestObserved'], .35)
        self.assertEqual(row['evidence']['MRI_HIPPOCAMPUS_L']['postIndexRows'], 1)

    def test_no_visits_produces_no_index_or_derived_feature_values(self):
        body = request()
        body['visits'] = []
        row = matrix(body)['rows'][0]
        self.assertIsNone(row['indexDate'])
        self.assertTrue(all(value is None for value in row['values'].values()))
        self.assertEqual(set(row['states'].values()), {'NO_INDEX'})
        self.assertEqual(row['evidence']['APOE_E4_COUNT']['unplacedRows'], 1)

    def test_blocked_request_can_describe_sources_without_producing_prediction(self):
        body = request()
        body['predictionWindowMonths'] = 12
        value = matrix(body)
        row = value['rows'][0]
        self.assertEqual(row['qualityStatus'], 'BLOCKED')
        self.assertIn('UNSUPPORTED_WINDOW', row['blockingReasons'])
        self.assertFalse(row['eligibleForExistingScoring'])
        self.assertEqual(row['values']['APOE_E4_COUNT.latestObserved'], 1)
        self.assertIsNone(row['evidence']['APOE_E4_COUNT']['currentScoringValue'])
        self.assertFalse(value['predictionProduced'])

    def test_apoe_has_no_numeric_trajectory_or_slope_columns(self):
        self.assertEqual([key for key in matrix()['columnOrder'] if key.startswith('APOE')], ['APOE_E4_COUNT.latestObserved'])

    def test_source_references_point_to_original_request_record_positions(self):
        body = request()
        body['visits'].reverse()
        value = matrix(body)
        row = value['rows'][0]
        self.assertEqual(row['requestDigest'], payload_digest(body))
        self.assertEqual(row['evidence']['mmse']['points'][0]['sources'], [{'table': 'visits', 'recordIndex': 2, 'field': 'mmse'}])
        self.assertTrue(all(p['availableDate'] is None for series in row['evidence'].values() for p in series['points']))

    def test_coverage_and_missing_matrix_are_aligned_per_subject_and_column(self):
        first, second = request(), request()
        second.update(subjectCode='DEMO-002', runId='run-second')
        second['features'] = []
        for visit in second['visits']:
            visit['mmse'] = None
        value = build_fusion_matrix([second, first])
        self.assertEqual([row['subjectCode'] for row in value['rows']], ['DEMO-001', 'DEMO-002'])
        key = 'APOE_E4_COUNT.latestObserved'
        index = value['columnOrder'].index(key)
        self.assertEqual([row[index] for row in value['missingMatrix']], [False, True])
        self.assertEqual(value['coverage'][index]['observedFraction'], .5)
        self.assertEqual(value['coverage'][index]['missingSubjects'], 1)

    def test_all_100_shipped_profiles_form_one_subject_level_matrix(self):
        rows = json.loads((ROOT / 'fixtures/synthetic_subjects_100.json').read_text(encoding='utf-8'))['subjects']
        value = build_fusion_matrix(rows)
        self.assertEqual(value['subjectCount'], 100)
        self.assertEqual(len(value['missingMatrix']), 100)
        self.assertTrue(all(len(row) == 26 for row in value['missingMatrix']))

    def test_duplicate_subject_or_run_is_not_counted_as_another_sample(self):
        for field in ('subjectCode', 'runId'):
            first, second = request(), request()
            second.update(subjectCode='DEMO-002', runId='run-second')
            second[field] = first[field]
            with self.assertRaises(FusionError) as error:
                build_fusion_matrix([first, second])
            self.assertEqual(error.exception.code, 'FUSION_DUPLICATE_BINDING')

    def test_mixed_data_versions_and_prediction_windows_are_rejected(self):
        for field, alternate in [('dataVersion', 'demo-other'), ('predictionWindowMonths', 12)]:
            first, second = request(), request()
            second.update(subjectCode='DEMO-002', runId='run-second')
            second[field] = alternate
            with self.assertRaises(FusionError) as error:
                build_fusion_matrix([first, second])
            self.assertEqual(error.exception.code, 'FUSION_MIXED_VERSIONS')

    def test_invalid_or_real_identifiers_are_rejected_without_echo(self):
        body = request()
        body['subjectCode'] = 'PRIVATE-DO-NOT-ECHO'
        with self.assertRaises(FusionError) as error:
            matrix(body)
        self.assertEqual(error.exception.code, 'FUSION_REQUEST_INVALID')
        self.assertNotIn('PRIVATE', str(error.exception))

    def test_window_configuration_rejects_booleans_and_inconsistent_spans(self):
        for kwargs in ({'lookback_days': True}, {'lookback_days': 0}, {'lookback_days': 3651},
                       {'min_span_days': 0}, {'lookback_days': 10, 'min_span_days': 30}):
            with self.assertRaises(FusionError) as error:
                matrix(**kwargs)
            self.assertEqual(error.exception.code, 'FUSION_WINDOW')

    def test_input_count_and_encoded_size_are_bounded(self):
        for rows in ([], [request()] * 201, None):
            with self.assertRaises(FusionError):
                build_fusion_matrix(rows)
        body = request()
        body['dataVersion'] = 'demo-' + 'x' * (1024 * 1024)
        with self.assertRaises(FusionError) as error:
            matrix(body)
        self.assertEqual(error.exception.code, 'FUSION_INPUT_SIZE')

    def test_nonfinite_and_surrogate_input_is_rejected_without_unsafe_json(self):
        for value in (float('nan'), float('inf'), '\ud800'):
            body = request()
            body['visits'][0]['mmse'] = value
            with self.assertRaises(FusionError):
                matrix(body)

    def test_output_and_input_objects_are_independent(self):
        body = request()
        before = copy.deepcopy(body)
        value = matrix(body)
        value['rows'][0]['evidence']['mmse']['points'][0]['value'] = 999
        value['featureDictionary'][0]['formula'] = 'changed'
        self.assertEqual(body, before)
        self.assertNotEqual(matrix(body)['featureDictionary'][0]['formula'], 'changed')

    def test_change_between_bounded_digest_and_snapshot_is_not_mislabelled(self):
        body = request()
        def changed(row):
            row['visits'][-1]['mmse'] = 0
            return request_snapshot(row)
        with patch('python_service.deepagent_contract.request_snapshot', side_effect=changed):
            with self.assertRaises(FusionError) as error:
                matrix(body)
        self.assertEqual(error.exception.code, 'FUSION_INPUT_CHANGED')

    def test_feature_builder_never_calls_workflow_scorer_network_or_files(self):
        body = request()
        with patch('python_service.deepagent_contract.run_workflow', side_effect=AssertionError('WORKFLOW')), \
             patch('python_service.demo_scoring.score_java_synthetic_payload', side_effect=AssertionError('SCORE')), \
             patch('builtins.open', side_effect=AssertionError('FILE')), \
             patch('http.client.HTTPConnection', side_effect=AssertionError('NETWORK')):
            value = matrix(body)
        for field in ('modelExecuted', 'modelFitted', 'predictionProduced', 'persisted', 'modelInputCompatible',
                      'sourceAuthenticityVerified', 'historicalAvailabilityVerified', 'clinicalValidityAssessed'):
            self.assertIs(value[field], False)
        self.assertEqual(value['imputedValues'], 0)

    def test_earliest_supported_date_does_not_underflow_lookback(self):
        body = request()
        body['visits'] = [dict(body['visits'][0], visitDate='0001-01-01')]
        row = matrix(body)['rows'][0]
        self.assertEqual(row['evidence']['mmse']['windowStart'], '0001-01-01')


if __name__ == '__main__':
    unittest.main()
