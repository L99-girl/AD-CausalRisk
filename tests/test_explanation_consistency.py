"""Constructed ranking, missingness, comparability and subject uncertainty cases."""
import copy
import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch

from python_service.explanation_consistency import (
    SCHEMA, ConsistencyError, compare_explanations, compare_panels, course_explanation,
)
from python_service.deepagent_contract import run_workflow
from python_service.demo_scoring import score_java_synthetic_payload
from python_service.course_protocol import CourseProtocolError

ROOT = Path(__file__).resolve().parents[1]


def record(values=(1., 2., 3.), subject='DEMO-001', **changes):
    terms = dict(zip(('a', 'b', 'c', 'd'), values))
    value = dict(schemaVersion=SCHEMA, mode='SYNTHETIC_DEMO', subjectCode=subject,
                 dataVersion='demo-test', observationSha256='a' * 64,
                 featureSchema='synthetic-terms-v1', target='synthetic-ranking-24m',
                 outputSpace='additive-score', reference='zero', unit='score',
                 modelVersion='synthetic-model-v1', methodVersion='synthetic-method-v1', fold='f1',
                 values=terms, missingReasons={key: 'UNOBSERVED' for key, x in terms.items() if x is None},
                 evidence={'kind': 'CALLER_DECLARED_SYNTHETIC', 'sha256': 'b' * 64})
    value.update(changes)
    return value


def request():
    return json.loads((ROOT / 'contracts/examples/deepagent-v1.request.example.json').read_text(encoding='utf-8'))


def compare(a, b, **kwargs):
    return compare_explanations(record(a), record(b), **kwargs)


class PairTests(unittest.TestCase):
    def test_identity_and_reversal(self):
        self.assertAlmostEqual(compare((1, 2, 3), (1, 2, 3))['spearmanSigned']['value'], 1)
        self.assertAlmostEqual(compare((1, 2, 3), (3, 2, 1))['spearmanSigned']['value'], -1)

    def test_average_tie_ranks_independent_hand_calculation(self):
        # [1, 2.5, 2.5, 4] versus [1, 2, 3, 4]: dot=4.5; sumsquares=4.5,5.
        self.assertAlmostEqual(compare((1, 2, 2, 3), (1, 2, 3, 4))['spearmanSigned']['value'],
                               4.5 / math.sqrt(4.5 * 5))

    def test_sign_flip_preserves_magnitude_but_not_signed_rank(self):
        value = compare((1, 2, 3), (-1, -2, -3))
        self.assertAlmostEqual(value['spearmanSigned']['value'], -1)
        self.assertAlmostEqual(value['spearmanMagnitude']['value'], 1)
        self.assertEqual(value['signChanges'], ['a', 'b', 'c'])

    def test_zero_is_observed_and_zero_transition_reported(self):
        value = compare((0, 1, 2), (1, 1, 2))
        self.assertEqual(value['sharedTermCount'], 3)
        self.assertEqual(value['missingLeft'], {})
        self.assertEqual(value['signChanges'], ['a'])

    def test_constant_and_single_feature_are_undefined(self):
        self.assertEqual(compare((0, 0, 0), (1, 2, 3))['spearmanSigned'],
                         {'value': None, 'reason': 'CONSTANT_RANKS'})
        self.assertEqual(compare((1,), (1,), top_k=1)['spearmanSigned']['reason'], 'INSUFFICIENT_SHARED_TERMS')

    def test_missing_pairwise_exclusion_never_zero_fill(self):
        value = compare((None, 2, 3), (1, 2, None))
        self.assertEqual(value['sharedTerms'], ['b'])
        self.assertIsNone(value['spearmanSigned']['value'])
        self.assertEqual(value['missingLeft'], {'a': 'UNOBSERVED'})

    def test_all_missing_top_k_is_not_perfect_agreement(self):
        value = compare((None, None, None), (None, None, None))
        self.assertIsNone(value['topK']['jaccard'])
        self.assertEqual(value['topK']['reason'], 'EMPTY_ARM')

    def test_cutoff_ties_keep_all_and_jaccard_uses_actual_union(self):
        value = compare((4, -3, 3, 1), (4, 2, 1, 3), top_k=2)['topK']
        self.assertEqual(value['left'], ['a', 'b', 'c'])
        self.assertEqual(value['right'], ['a', 'd'])
        self.assertEqual(value['intersection'], ['a'])
        self.assertEqual(value['jaccard'], .25)

    def test_top_sets_include_missing_arm_disagreement(self):
        value = compare((5, 2, 1), (None, 2, 1), top_k=1)['topK']
        self.assertEqual(value['jaccard'], 0)
        self.assertEqual(value['left'], ['a'])
        self.assertEqual(value['right'], ['b'])

    def test_fewer_available_than_k_reported(self):
        self.assertTrue(compare((None, 2, None), (1, 2, 3))['topK']['fewerThanKLeft'])

    def test_order_is_irrelevant(self):
        a, b = record(), record()
        b['values'] = dict(reversed(list(b['values'].items())))
        self.assertEqual(compare_explanations(a, b), compare_explanations(a, a))

    def test_models_methods_folds_are_declared_dimensions(self):
        value = compare_explanations(record(), record(modelVersion='synthetic-model-v2',
                                    methodVersion='synthetic-method-v2', fold='f2'))
        self.assertNotEqual(value['leftArm'], value['rightArm'])
        self.assertFalse(value['researchAcceptanceEstablished'])

    def test_context_mismatches_rejected_individually(self):
        for key in ('dataVersion', 'observationSha256', 'featureSchema', 'target', 'outputSpace', 'reference', 'unit'):
            with self.subTest(key=key), self.assertRaisesRegex(ConsistencyError, 'CONTEXT_MISMATCH'):
                compare_explanations(record(), record(**{key: 'b' * 64 if key == 'observationSha256' else 'demo-other'}))

    def test_subject_or_feature_universe_mismatch_rejected(self):
        for other in (record(subject='DEMO-002'), record((1, 2))):
            with self.assertRaises(ConsistencyError):
                compare_explanations(record(), other)

    def test_missing_requires_reasons_and_no_spurious_reasons(self):
        for other in (record((None, 2, 3), missingReasons={}), record(missingReasons={'a': 'no'})):
            with self.assertRaisesRegex(ConsistencyError, 'MISSING_REASONS'):
                compare_explanations(record(), other)

    def test_invalid_numbers_unicode_and_oversized_inputs_rejected(self):
        for value in (True, float('nan'), float('inf'), 10**400):
            with self.subTest(value=type(value).__name__), self.assertRaises(ConsistencyError):
                compare((value, 2, 3), (1, 2, 3))
        for other in (record(subject='REAL-001'), record(mode='RESEARCH'),
                      record(fold='\ud800'), record(evidence={}),
                      record(values={'x': 'x' * (2 * 1024 * 1024)})):
            with self.assertRaises(ConsistencyError):
                compare_explanations(record(), other)

    def test_configuration_and_extra_fields_rejected(self):
        for k in (True, 0, 4, 1.5):
            with self.assertRaises(ConsistencyError):
                compare_explanations(record(), record(), top_k=k)
        with self.assertRaisesRegex(ConsistencyError, 'RECORD_FIELDS'):
            compare_explanations(record(), record(extra=True))

    def test_inputs_and_outputs_are_detached_and_json_safe(self):
        a, b = record((None, 2, 3)), record()
        before = copy.deepcopy([a, b])
        value = compare_explanations(a, b)
        value['missingLeft']['a'] = 'changed'
        self.assertEqual([a, b], before)
        json.dumps(value, allow_nan=False)


class CourseAdapterTests(unittest.TestCase):
    def test_original_result_values_and_observation_identity_without_scorer(self):
        body = request()
        result = run_workflow(body, score_java_synthetic_payload)
        before = copy.deepcopy([body, result])
        with patch('python_service.demo_scoring.score_java_synthetic_payload', side_effect=AssertionError('no scoring')):
            adapted = course_explanation(body, result)
        self.assertEqual({key: x for key, x in adapted['values'].items() if x is not None},
                         {row['feature']: row['contribution'] for row in result['explanations']})
        self.assertEqual([body, result], before)
        body['runId'] = 'run-repeated'
        repeated = course_explanation(body, run_workflow(body, score_java_synthetic_payload))
        self.assertEqual(adapted['observationSha256'], repeated['observationSha256'])
        self.assertNotEqual(adapted['evidence'], repeated['evidence'])

    def test_tampered_result_is_rejected_by_original_validation(self):
        body = request()
        result = run_workflow(body, score_java_synthetic_payload)
        result['explanations'][0]['contribution'] += .01
        with self.assertRaises(CourseProtocolError):
            course_explanation(body, result)

    def test_blocked_has_null_terms_and_reason(self):
        body = request()
        body['predictionWindowMonths'] = 12
        adapted = course_explanation(body, run_workflow(body, score_java_synthetic_payload))
        self.assertEqual(set(adapted['values'].values()), {None})
        self.assertEqual(set(adapted['missingReasons'].values()), {'QUALITY_BLOCKED'})

    def test_different_observations_rejected(self):
        a, b = request(), request()
        b['visits'][-1]['mmse'] = 24
        av = course_explanation(a, run_workflow(a, score_java_synthetic_payload))
        bv = course_explanation(b, run_workflow(b, score_java_synthetic_payload))
        with self.assertRaisesRegex(ConsistencyError, 'CONTEXT_MISMATCH'):
            compare_explanations(av, bv)

    def test_missing_cognition_and_right_mri_fallback_keep_original_term_semantics(self):
        body = request()
        body['visits'][-1]['mmse'] = None
        body['features'] = body['features'][::2]  # APOE and right MRI only
        adapted = course_explanation(body, run_workflow(body, score_java_synthetic_payload))
        self.assertIsNone(adapted['values']['MMSE'])
        self.assertIsNone(adapted['values']['MMSE_DELTA'])
        self.assertEqual(adapted['values']['MRI_HIPPOCAMPUS'], .0132)


class PanelTests(unittest.TestCase):
    def test_pair_by_subject_not_position_and_report_unmatched(self):
        left = [record(subject='DEMO-002'), record(subject='DEMO-001')]
        right = [record(subject='DEMO-003'), record(subject='DEMO-002')]
        value = compare_panels(left, right, resamples=200)
        self.assertEqual(value['pairedSubjects'], 1)
        self.assertEqual(value['pairs'][0]['subjectCode'], 'DEMO-002')
        self.assertEqual(value['leftOnly'], ['DEMO-001'])
        self.assertEqual(value['rightOnly'], ['DEMO-003'])
        self.assertIsNone(value['summary']['spearmanSigned']['interval95'])

    def test_duplicate_subjects_cannot_pseudoreplicate(self):
        with self.assertRaisesRegex(ConsistencyError, 'DUPLICATE_SUBJECT'):
            compare_panels([record(), record()], [record()])

    def test_mixed_model_method_fold_or_context_panel_rejected(self):
        for key in ('modelVersion', 'methodVersion', 'fold', 'dataVersion', 'target'):
            with self.subTest(key=key), self.assertRaisesRegex(ConsistencyError, 'MIXED_PANEL'):
                compare_panels([record(), record(subject='DEMO-002', **{key: 'demo-other'})], [record()])

    def test_different_subject_observation_digests_allowed_within_panel(self):
        panel = [record(), record(subject='DEMO-002', observationSha256='b' * 64)]
        self.assertEqual(compare_panels(panel, panel, resamples=200)['pairedSubjects'], 2)

    def test_fixed_seed_and_reordering_preserve_statistics(self):
        left = [record(subject=f'DEMO-{i}') for i in range(4)]
        right = [record(v, subject=f'DEMO-{i}') for i, v in enumerate(((1, 2, 3), (3, 2, 1), (2, 1, 3), (1, 3, 2)))]
        a = compare_panels(left, right, resamples=200, seed=42)
        b = compare_panels(list(reversed(left)), list(reversed(right)), resamples=200, seed=42)
        self.assertEqual(a['summary'], b['summary'])
        self.assertEqual(a['pairs'], b['pairs'])
        self.assertEqual(a['uncertainty']['resamplingUnit'], 'UNIQUE_PAIRED_SUBJECT')
        self.assertFalse(a['uncertainty']['populationInferenceEstablished'])
        self.assertAlmostEqual(a['summary']['spearmanSigned']['mean'], .25)

    def test_undefined_subjects_have_separate_metric_denominators(self):
        left = [record((0, 0, 0)), record(subject='DEMO-002')]
        right = [record(), record(subject='DEMO-002')]
        value = compare_panels(left, right, resamples=200)
        self.assertEqual(value['summary']['spearmanSigned']['definedSubjects'], 1)
        self.assertEqual(value['summary']['spearmanSigned']['undefinedSubjects'], 1)
        self.assertEqual(value['summary']['topKJaccard']['definedSubjects'], 2)

    def test_disjoint_subjects_have_no_score_and_no_interval(self):
        value = compare_panels([record()], [record(subject='DEMO-002')])
        self.assertEqual(value['pairedSubjects'], 0)
        self.assertIsNone(value['summary']['topKJaccard']['mean'])
        self.assertIsNone(value['summary']['topKJaccard']['interval95'])

    def test_invalid_panel_configuration_rejected(self):
        for kwargs in ({'resamples': 199}, {'resamples': True}, {'resamples': 2001},
                       {'seed': -1}, {'seed': 2**32}, {'seed': True}, {'top_k': 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ConsistencyError):
                compare_panels([record()], [record()], **kwargs)
        for panel in ([], [record()] * 201, (record(),)):
            with self.assertRaises(ConsistencyError):
                compare_panels(panel, [record()])

    def test_100_shipped_profiles_validated_and_paired_without_models(self):
        bodies = json.loads((ROOT / 'fixtures/synthetic_subjects_100.json').read_text(encoding='utf-8'))['subjects']
        panel = [course_explanation(body, run_workflow(body, score_java_synthetic_payload)) for body in bodies]
        value = compare_panels(panel, list(reversed(panel)), resamples=200)
        self.assertEqual(value['pairedSubjects'], 100)
        for metric in value['summary'].values():
            self.assertAlmostEqual(metric['mean'], 1)
            for bound in metric['interval95']:
                self.assertAlmostEqual(bound, 1)
        self.assertFalse(value['modelExecuted'])
        json.dumps(value, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
