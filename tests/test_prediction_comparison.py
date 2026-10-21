"""Known net benefits and correctly paired subject bootstrap behavior."""
import copy
import json
import math
import unittest

from python_service.prediction_comparison import decision_curve, compare_prediction_panels
from python_service.prediction_evaluation import EvaluationError
from test_prediction_evaluation import protocol, panel


class DecisionCurveTests(unittest.TestCase):
    def test_hand_computed_model_all_and_none_benefits(self):
        value = decision_curve(protocol(), panel())
        a, b = value['curves']
        self.assertEqual((a['tp'], a['fp']), (2, 1))
        self.assertAlmostEqual(a['modelNetBenefit'], .5 - .25 * .35 / .65)
        self.assertAlmostEqual(a['treatAllNetBenefit'], .5 - .5 * .35 / .65)
        self.assertEqual(a['treatNoneNetBenefit'], 0)
        self.assertEqual(b['modelNetBenefit'], .25)
        self.assertEqual(b['treatAllNetBenefit'], 0)
        self.assertEqual(value['subjects'], 4)

    def test_threshold_equality_is_positive(self):
        p = dict(protocol(), thresholds=[.5])
        value = decision_curve(p, panel(p, probabilities=(.5,) * 4))['curves'][0]
        self.assertEqual((value['tp'], value['fp']), (2, 2))
        self.assertEqual(value['modelNetBenefit'], 0)

    def test_negative_benefit_never_clamped_or_turned_into_a_probability(self):
        value = decision_curve(protocol(), panel(probabilities=(1, 1, 0, 0)))
        self.assertLess(value['curves'][1]['modelNetBenefit'], 0)
        self.assertIsNone(value['clinicalThresholdRecommendation'])
        self.assertFalse(value['clinicalUtilityEstablished'])

    def test_no_events_retains_valid_dca_even_when_auc_undefined(self):
        p = dict(protocol(), thresholds=[.5])
        value = decision_curve(p, panel(p, outcomes=(0,) * 4, probabilities=(1,) * 4))
        self.assertEqual(value['eventCount'], 0)
        self.assertEqual(value['curves'][0]['modelNetBenefit'], -1)
        self.assertEqual(value['curves'][0]['treatAllNetBenefit'], -1)

    def test_predeclared_threshold_only_no_tuning_and_no_course_adapter(self):
        p = dict(protocol(), thresholds=[.123, .456, .789])
        value = decision_curve(p, panel(p))
        self.assertEqual([row['threshold'] for row in value['curves']], p['thresholds'])
        self.assertNotIn('bestThreshold', value)
        with self.assertRaises(EvaluationError):
            decision_curve(p, {'riskScore': .5, 'status': 'COMPLETED'})

    def test_extreme_allowed_threshold_is_finite(self):
        p = dict(protocol(), thresholds=[.9999999999999999])
        value = decision_curve(p, panel(p, outcomes=(0,) * 4, probabilities=(1,) * 4))
        self.assertTrue(math.isfinite(value['curves'][0]['modelNetBenefit']))
        json.dumps(value, allow_nan=False)


class PairedComparisonTests(unittest.TestCase):
    def test_hand_computed_right_minus_left_differences(self):
        p, a = protocol(), panel()
        b = panel(p, probabilities=(.1, .2, .7, .9), version='demo-model-b')
        value = compare_prediction_panels(p, a, b, resamples=200, seed=42)
        self.assertEqual(value['differenceDefinition'], 'RIGHT_MINUS_LEFT')
        self.assertAlmostEqual(value['metricDifferences']['rocAuc']['observedDifference'], .25)
        self.assertAlmostEqual(value['metricDifferences']['averagePrecision']['observedDifference'], 1 / 6)
        self.assertAlmostEqual(value['metricDifferences']['brier']['observedDifference'], .0375 - .158125)
        self.assertAlmostEqual(value['decisionCurveDifferences'][0]['observedDifference'], .25 * .35 / .65)
        self.assertAlmostEqual(value['decisionCurveDifferences'][1]['observedDifference'], .25)

    def test_same_panel_has_zero_differences_and_intervals_when_defined(self):
        p, a = protocol(), panel()
        value = compare_prediction_panels(p, a, a, resamples=200)
        for row in list(value['metricDifferences'].values()) + value['decisionCurveDifferences']:
            self.assertEqual(row['observedDifference'], 0)
            self.assertEqual(row['interval95'], [0, 0])

    def test_exact_two_subject_bootstrap_auc_interval_and_undefined_counts(self):
        p = protocol(subjects=['DEMO-A', 'DEMO-B'])
        a = panel(p, probabilities=(.8, .2), outcomes=(0, 1))
        b = panel(p, probabilities=(.2, .8), outcomes=(0, 1), version='demo-model-b')
        value = compare_prediction_panels(p, a, b, resamples=200, seed=11)
        auc = value['metricDifferences']['rocAuc']
        self.assertEqual(auc['observedDifference'], 1)
        self.assertEqual(auc['interval95'], [1, 1])
        self.assertGreater(auc['undefinedReplicates'], 0)
        self.assertEqual(auc['definedReplicates'] + auc['undefinedReplicates'], 200)
        self.assertEqual(value['metricDifferences']['brier']['definedReplicates'], 200)
        for bound in value['metricDifferences']['brier']['interval95']:
            self.assertAlmostEqual(bound, -.6)

    def test_order_and_seed_are_reproducible(self):
        p, a = protocol(), panel()
        b = panel(p, probabilities=(.1, .2, .7, .9), version='demo-model-b')
        first = compare_prediction_panels(p, a, b, resamples=200, seed=7)
        a['predictions'].reverse()
        b['predictions'] = b['predictions'][1:] + b['predictions'][:1]
        second = compare_prediction_panels(p, a, b, resamples=200, seed=7)
        self.assertEqual(first['metricDifferences'], second['metricDifferences'])
        self.assertEqual(first['decisionCurveDifferences'], second['decisionCurveDifferences'])
        self.assertEqual(first['pairedSubjectCodes'], second['pairedSubjectCodes'])

    def test_reversing_models_reverses_differences_and_interval_bounds(self):
        p, a = protocol(), panel()
        b = panel(p, probabilities=(.1, .2, .7, .9), version='demo-model-b')
        forward = compare_prediction_panels(p, a, b, resamples=200, seed=7)
        backward = compare_prediction_panels(p, b, a, resamples=200, seed=7)
        for key in forward['metricDifferences']:
            f, b = forward['metricDifferences'][key], backward['metricDifferences'][key]
            self.assertAlmostEqual(f['observedDifference'], -b['observedDifference'])
            self.assertAlmostEqual(f['interval95'][0], -b['interval95'][1])
            self.assertAlmostEqual(f['interval95'][1], -b['interval95'][0])

    def test_changed_outcome_for_same_subject_rejected(self):
        a, b = panel(), panel(version='demo-model-b')
        b['predictions'][0]['outcome'] = 1
        with self.assertRaisesRegex(EvaluationError, 'PAIRED_OUTCOME_MISMATCH'):
            compare_prediction_panels(protocol(), a, b, resamples=200)

    def test_subset_extra_duplicate_wrong_fold_or_protocol_rejected(self):
        p, a = protocol(), panel()
        for mode in ('missing', 'extra', 'duplicate', 'fold', 'protocol'):
            b = panel(version='demo-model-b')
            if mode == 'missing':
                b['predictions'].pop()
            elif mode == 'extra':
                b['predictions'].append(dict(b['predictions'][0], subjectCode='DEMO-EXTRA'))
            elif mode == 'duplicate':
                b['predictions'][0] = dict(b['predictions'][1])
            elif mode == 'fold':
                b['predictions'][0]['foldId'] = 'demo-wrong'
            else:
                b['protocolSha256'] = '0' * 64
            with self.subTest(mode=mode), self.assertRaises(EvaluationError):
                compare_prediction_panels(p, a, b, resamples=200)

    def test_single_class_auc_ap_have_no_fabricated_interval(self):
        a = panel(outcomes=(0,) * 4)
        b = panel(outcomes=(0,) * 4, probabilities=(.1, .2, .3, .4), version='demo-model-b')
        value = compare_prediction_panels(protocol(), a, b, resamples=200)
        for key in ('rocAuc', 'averagePrecision', 'prAucTrapezoidal'):
            row = value['metricDifferences'][key]
            self.assertIsNone(row['observedDifference'])
            self.assertIsNone(row['interval95'])
            self.assertEqual(row['undefinedReplicates'], 200)
        self.assertIsNotNone(value['metricDifferences']['brier']['interval95'])

    def test_one_subject_has_no_fake_interval_despite_many_draws(self):
        p = protocol(subjects=['DEMO-ONLY'])
        a, b = panel(p, probabilities=(.2,), outcomes=(1,)), panel(p, probabilities=(.8,), outcomes=(1,))
        value = compare_prediction_panels(p, a, b, resamples=200)
        row = value['metricDifferences']['brier']
        self.assertEqual(row['definedReplicates'], 200)
        self.assertIsNone(row['interval95'])
        self.assertEqual(row['intervalReason'], 'INSUFFICIENT_SUBJECTS')

    def test_oof_sampling_unit_is_subject_not_fold_or_visit(self):
        p = protocol(split_type='OOF')
        a, b = panel(p), panel(p, probabilities=(.1, .2, .7, .9), version='demo-model-b')
        value = compare_prediction_panels(p, a, b, resamples=200)
        self.assertEqual(value['pairedSubjects'], 4)
        self.assertEqual(value['uncertainty']['resamplingUnit'], 'UNIQUE_SUBJECT')
        self.assertFalse(value['uncertainty']['modelRefitted'])
        self.assertFalse(value['uncertainty']['intervalsAreSimultaneous'])

    def test_invalid_resample_configuration_rejected(self):
        for kwargs in ({'resamples': True}, {'resamples': 199}, {'resamples': 2001}, {'resamples': 200.},
                       {'seed': -1}, {'seed': True}, {'seed': 2**32}):
            with self.subTest(kwargs=kwargs), self.assertRaises(EvaluationError):
                compare_prediction_panels(protocol(), panel(), panel(), **kwargs)

    def test_no_input_mutation_no_acceptance_no_nan(self):
        p, a, b = protocol(), panel(), panel(version='demo-model-b')
        before = copy.deepcopy([p, a, b])
        value = compare_prediction_panels(p, a, b, resamples=200)
        self.assertEqual([p, a, b], before)
        value['limitations'].clear()
        self.assertTrue(compare_prediction_panels(p, a, b, resamples=200)['limitations'])
        for key in ('modelExecuted', 'modelFitted', 'predictionProduced', 'recalibrated', 'persisted',
                    'researchAcceptanceEstablished', 'clinicalValidityEstablished', 'clinicalUtilityEstablished'):
            self.assertFalse(value[key])
        self.assertIsNone(value['clinicalThresholdRecommendation'])
        json.dumps(value, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
