"""Do not misreport transport errors or malformed evidence as passed validation."""
import copy
import unittest
from python_service.demo_task_feedback import expected_rejection, training_summary, SCENARIOS, VARIANTS


def rejection(scenario='invalid_mmse'):
    rule = SCENARIOS[scenario]
    return {'input_mode': 'SYNTHETIC_TEST', 'variant': 'trajectory_graph', 'status': 'FAILED',
            'scenario': scenario, 'result': None,
            'error': {'code': rule['code'], 'upstream_http_status': rule['http']}}


def manifest():
    return {'status': 'verified_fixed_specification_reproduction', 'models': dict.fromkeys(VARIANTS),
            'new_fixed_specification_fits': 6, 'training_subjects': 451, 'training_person_months': 9082,
            'clinical_use_established': False, 'individual_causal_effect_identified': False,
            'verification': {'metric_comparisons': 90, 'paired_comparisons': 15,
                             'maximum_metric_difference': 0., 'maximum_paired_difference': 0.,
                             'maximum_serialization_prediction_difference': 0.,
                             'solver_iterations_match_original': True}}


class FeedbackTests(unittest.TestCase):
    def test_all_four_exact_rejections_are_expected(self):
        for scenario in SCENARIOS:
            if scenario != 'valid':
                with self.subTest(scenario=scenario):self.assertTrue(expected_rejection(rejection(scenario)))

    def test_service_failure_is_not_a_passed_negative_test(self):
        task = rejection(); task['error'] = {'code': 'MODEL_COMPUTATION_UNAVAILABLE', 'upstream_http_status': 503}
        self.assertFalse(expected_rejection(task))

    def test_another_validation_failure_is_not_the_expected_failure(self):
        task = rejection(); task['error']['code'] = 'MISSING_GRAPH_AVAILABILITY'
        self.assertFalse(expected_rejection(task))

    def test_wrong_or_missing_http_evidence_is_not_expected(self):
        for value in (None, '400', True, 400., 403, 503):
            task = rejection(); task['error']['upstream_http_status'] = value
            with self.subTest(value=value):self.assertFalse(expected_rejection(task))

    def test_success_partial_result_and_real_input_are_never_expected_rejections(self):
        for changes in ({'status': 'COMPLETED'}, {'status': 'RUNNING'}, {'status': 'CANCELLED'},
                        {'result': {}}, {'input_mode': 'REAL_RETROSPECTIVE_RESEARCH'},
                        {'variant': 'unknown'}, {'scenario': 'valid'}, {'scenario': 'unknown'}):
            task = rejection(); task.update(changes)
            with self.subTest(changes=changes):self.assertFalse(expected_rejection(task))

    def test_list_summaries_and_missing_errors_do_not_certify_expected_rejection(self):
        for task in ({}, {'scenario': 'invalid_mmse', 'status': 'FAILED'},
                     {**rejection(), 'error': None}, {**rejection(), 'error': []}):
            self.assertFalse(expected_rejection(task))

    def test_classification_preserves_original_task_and_status(self):
        task = rejection(); before = copy.deepcopy(task)
        expected_rejection(task)
        self.assertEqual(task, before); self.assertEqual(task['status'], 'FAILED')

    def test_model_summary_reports_reproduction_and_loading_distinction(self):
        summary = training_summary(manifest())
        for text in ('451', '9082', '6 种固定输入方案', '90', '15', '未加载不等于未训练', '尚未确立'):
            self.assertIn(text, summary)

    def test_missing_metadata_does_not_claim_training_complete(self):
        for value in ({}, None, {'verification': {}}):
            self.assertIn('无法确认训练状态', training_summary(value))

    def test_nonzero_nan_and_boolean_differences_do_not_claim_verified_reproduction(self):
        for key in ('maximum_metric_difference', 'maximum_paired_difference', 'maximum_serialization_prediction_difference'):
            for value in (.001, float('nan'), False, '0'):
                source = manifest(); source['verification'][key] = value
                with self.subTest(key=key,value=value):self.assertIn('无法确认训练状态', training_summary(source))

    def test_incomplete_models_and_invalid_counts_do_not_claim_complete_training(self):
        for changes in ({'models': {}}, {'training_subjects': True}, {'training_person_months': 0},
                        {'new_fixed_specification_fits': 5}, {'training_subjects': '451'}):
            source = manifest(); source.update(changes)
            self.assertIn('无法确认训练状态', training_summary(source))

    def test_unexpected_clinical_or_causal_flags_do_not_become_validated_claims(self):
        for key in ('clinical_use_established', 'individual_causal_effect_identified'):
            source = manifest(); source[key] = True
            self.assertIn('无法确认训练状态', training_summary(source))


if __name__ == '__main__':unittest.main()
