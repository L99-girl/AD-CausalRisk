"""Constructed protocol, subject grouping and independently known metrics."""
import copy
from fractions import Fraction
import json
import unittest

from python_service.prediction_evaluation import (
    PROTOCOL_SCHEMA, PANEL_SCHEMA, EvaluationError, evaluate_predictions,
    protocol_sha256, validate_evaluation_protocol,
)


def protocol(subjects=None, split_type='HOLDOUT'):
    subjects = subjects or [f'DEMO-EVAL-{i}' for i in range(4)]
    if split_type == 'OOF':
        splits = [{'foldId': f'demo-fold-{i}', 'trainSubjects': subjects[1 - i::2],
                   'testSubjects': subjects[i::2]} for i in range(2)]
    else:
        splits = [{'foldId': 'demo-holdout', 'trainSubjects': ['DEMO-TRAIN-1', 'DEMO-TRAIN-2'],
                   'testSubjects': list(subjects)}]
    return {'schemaVersion': PROTOCOL_SCHEMA, 'mode': 'SYNTHETIC_TEST',
            'protocolVersion': 'demo-eval-v1', 'dataVersion': 'demo-eval-data-v1',
            'endpointId': 'demo-binary-complete-event', 'horizonMonths': 24,
            'labelPolicy': 'CONSTRUCTED_COMPLETE_BINARY_NO_CENSORING', 'splitType': split_type,
            'evaluationSubjects': list(subjects), 'splits': splits, 'thresholds': [.35, .5],
            'calibrationBinEdges': [0., .5, 1.]}


def panel(p=None, probabilities=(.1, .4, .35, .8), outcomes=(0, 0, 1, 1), version='demo-model-a'):
    p = protocol() if p is None else p
    folds = {subject: split['foldId'] for split in p['splits'] for subject in split['testSubjects']}
    return {'schemaVersion': PANEL_SCHEMA, 'mode': 'SYNTHETIC_TEST', 'protocolSha256': protocol_sha256(p),
            'modelVersion': version, 'source': 'CONSTRUCTED_TEST_VECTOR',
            'predictions': [{'subjectCode': subject, 'foldId': folds[subject], 'outcome': outcome, 'probability': score}
                            for subject, score, outcome in zip(p['evaluationSubjects'], probabilities, outcomes)]}


class ProtocolTests(unittest.TestCase):
    def test_holdout_and_oof_valid_declarations_detached(self):
        for kind in ('HOLDOUT', 'OOF'):
            p = protocol(split_type=kind)
            before = copy.deepcopy(p)
            value = validate_evaluation_protocol(p)
            self.assertEqual(value, p)
            value['evaluationSubjects'].append('DEMO-EXTRA')
            self.assertEqual(p, before)
            context = evaluate_predictions(p, panel(p))['context']
            self.assertTrue(context['declaredSubjectDisjointnessChecked'])
            self.assertFalse(context['actualTrainingMembershipVerified'])
            self.assertFalse(context['outOfFoldPredictionsVerified'])

    def test_train_test_subject_leakage_rejected_in_any_fold(self):
        for kind in ('HOLDOUT', 'OOF'):
            p = protocol(split_type=kind)
            p['splits'][0]['trainSubjects'].append(p['splits'][0]['testSubjects'][0])
            with self.assertRaisesRegex(EvaluationError, 'TRAIN_TEST_SUBJECT_LEAKAGE'):
                validate_evaluation_protocol(p)

    def test_duplicate_subject_lists_rejected(self):
        for where in ('evaluation', 'train', 'test'):
            p = protocol()
            values = p['evaluationSubjects'] if where == 'evaluation' else p['splits'][0][where + 'Subjects']
            values.append(values[0])
            with self.assertRaisesRegex(EvaluationError, 'DUPLICATE_SUBJECT'):
                validate_evaluation_protocol(p)

    def test_test_coverage_duplicate_fold_and_duplicate_assignment_rejected(self):
        for mode in ('missing', 'fold', 'assignment', 'unknown'):
            p = protocol(split_type='OOF')
            if mode == 'missing':
                p['splits'][0]['testSubjects'].pop()
            elif mode == 'fold':
                p['splits'][1]['foldId'] = p['splits'][0]['foldId']
            elif mode == 'assignment':
                item = p['splits'][0]['testSubjects'][0]
                p['splits'][1]['trainSubjects'].remove(item)
                p['splits'][1]['testSubjects'].append(item)
            else:
                p['splits'][0]['testSubjects'].append('DEMO-NOT-EVALUATED')
            with self.subTest(mode=mode), self.assertRaises(EvaluationError):
                validate_evaluation_protocol(p)

    def test_invalid_split_counts_and_empty_groups_rejected(self):
        for p in (dict(protocol(), splits=[]), dict(protocol(), splitType='OOF'),
                  dict(protocol(), splitType='random-rows'), dict(protocol(), evaluationSubjects=[])):
            with self.assertRaises(EvaluationError):
                validate_evaluation_protocol(p)
        for field in ('trainSubjects', 'testSubjects'):
            p = protocol()
            p['splits'][0][field] = []
            with self.assertRaises(EvaluationError):
                validate_evaluation_protocol(p)

    def test_temporal_or_survival_endpoint_not_silently_reinterpreted(self):
        for field, value in (('horizonMonths', 12), ('horizonMonths', True),
                             ('labelPolicy', 'CENSORED'), ('mode', 'REAL_RESEARCH'),
                             ('endpointId', 'NACC-real-endpoint'), ('dataVersion', 'private-v1')):
            with self.subTest(field=field), self.assertRaises(EvaluationError):
                validate_evaluation_protocol(dict(protocol(), **{field: value}))

    def test_invalid_thresholds_and_bin_edges_rejected(self):
        for thresholds in ([], [0], [1], [True], [.5, .5], [.8, .2], [float('nan')]):
            with self.assertRaises(EvaluationError):
                validate_evaluation_protocol(dict(protocol(), thresholds=thresholds))
        for edges in ([0], [.1, 1], [0, .8], [0, .5, .5, 1], [0, 1, .5], [False, 1]):
            with self.assertRaises(EvaluationError):
                validate_evaluation_protocol(dict(protocol(), calibrationBinEdges=edges))

    def test_unknown_fields_and_bad_shapes_rejected(self):
        for value in (None, [], {}, dict(protocol(), extra='not-allowed')):
            with self.assertRaises(EvaluationError):
                validate_evaluation_protocol(value)
        p = protocol()
        p['splits'][0]['extra'] = True
        with self.assertRaises(EvaluationError):
            validate_evaluation_protocol(p)

    def test_unicode_oversize_and_non_demo_subject_rejected(self):
        for field, value in (('protocolVersion', '\ud800'), ('dataVersion', 'x' * (1024 * 1024))):
            with self.assertRaises(EvaluationError):
                validate_evaluation_protocol(dict(protocol(), **{field: value}))
        p = protocol()
        p['evaluationSubjects'][0] = 'REAL-001'
        with self.assertRaises(EvaluationError):
            validate_evaluation_protocol(p)


class PanelTests(unittest.TestCase):
    def test_panel_requires_exact_protocol_and_constructed_probability_source(self):
        for field, value in (('protocolSha256', 'a' * 64), ('source', 'COURSE_RISK_SCORE'),
                             ('mode', 'SYNTHETIC_DEMO'), ('modelVersion', 'deepagent-causal-warning-v1'),
                             ('schemaVersion', 'AgentResult')):
            with self.subTest(field=field), self.assertRaises(EvaluationError):
                evaluate_predictions(protocol(), dict(panel(), **{field: value}))

    def test_wrong_subject_duplicate_missing_or_wrong_fold_rejected(self):
        for mode in ('subject', 'duplicate', 'missing', 'fold'):
            v = panel()
            if mode == 'subject':
                v['predictions'][0]['subjectCode'] = 'DEMO-UNKNOWN'
            elif mode == 'duplicate':
                v['predictions'][0] = dict(v['predictions'][1])
            elif mode == 'missing':
                v['predictions'].pop()
            else:
                v['predictions'][0]['foldId'] = 'demo-wrong-fold'
            with self.subTest(mode=mode), self.assertRaises(EvaluationError):
                evaluate_predictions(protocol(), v)

    def test_unknown_outcomes_and_invalid_probabilities_rejected(self):
        for field, values in (('outcome', [None, True, .0, 2, -1, '1']),
                              ('probability', [None, True, -0.1, 1.1, float('inf'), 10**400])):
            for value in values:
                v = panel()
                v['predictions'][0][field] = value
                with self.subTest(field=field, value=type(value).__name__), self.assertRaises(EvaluationError):
                    evaluate_predictions(protocol(), v)

    def test_complete_coverage_not_best_case_subset_required(self):
        p = protocol()
        v = panel(p)
        v['predictions'] = v['predictions'][1:]
        with self.assertRaisesRegex(EvaluationError, 'PREDICTION_COVERAGE'):
            evaluate_predictions(p, v)

    def test_model_or_protocol_changes_bound_to_digest(self):
        p, v = protocol(), panel()
        p['thresholds'] = [.2, .5]
        with self.assertRaisesRegex(EvaluationError, 'PROTOCOL_BINDING'):
            evaluate_predictions(p, v)

    def test_prediction_order_does_not_affect_metrics(self):
        p, v = protocol(), panel()
        a = evaluate_predictions(p, v)
        v['predictions'].reverse()
        b = evaluate_predictions(p, v)
        self.assertEqual(a['metrics'], b['metrics'])
        self.assertNotEqual(a['panelSha256'], b['panelSha256'])

    def test_inputs_and_limitations_are_detached(self):
        p, v = protocol(), panel()
        before = copy.deepcopy([p, v])
        a = evaluate_predictions(p, v)
        a['limitations'].clear()
        a['metrics']['calibration']['bins'][0]['count'] = 999
        self.assertEqual([p, v], before)
        self.assertTrue(evaluate_predictions(p, v)['limitations'])


class MetricsTests(unittest.TestCase):
    def test_hand_calculated_auc_ap_pr_area_brier_and_confusion(self):
        m = evaluate_predictions(protocol(), panel())['metrics']
        self.assertEqual(m['rocAuc'], .75)
        self.assertAlmostEqual(m['averagePrecision'], float(Fraction(5, 6)))
        self.assertAlmostEqual(m['prAucTrapezoidal'], float(Fraction(19, 24)))
        self.assertAlmostEqual(m['brier'], .158125)
        a, b = m['classification']
        self.assertEqual([a[k] for k in ('tp', 'fp', 'tn', 'fn')], [2, 1, 1, 0])
        self.assertEqual([b[k] for k in ('tp', 'fp', 'tn', 'fn')], [1, 0, 2, 1])
        self.assertEqual(a['sensitivity'], 1)
        self.assertEqual(b['specificity'], 1)

    def test_tied_scores_use_half_credit_and_grouped_pr_steps(self):
        m = evaluate_predictions(protocol(), panel(probabilities=(.5,) * 4))['metrics']
        self.assertEqual(m['rocAuc'], .5)
        self.assertEqual(m['averagePrecision'], .5)
        self.assertEqual(m['prAucTrapezoidal'], .75)
        self.assertEqual(m['brier'], .25)

    def test_perfect_and_reversed_probability_order(self):
        perfect = evaluate_predictions(protocol(), panel(probabilities=(0, 0, 1, 1)))['metrics']
        reversed_ = evaluate_predictions(protocol(), panel(probabilities=(1, 1, 0, 0)))['metrics']
        self.assertEqual(perfect['rocAuc'], 1)
        self.assertEqual(perfect['brier'], 0)
        self.assertEqual(reversed_['rocAuc'], 0)
        self.assertEqual(reversed_['brier'], 1)

    def test_no_events_or_no_non_events_preserve_undefined_rates(self):
        negative = evaluate_predictions(protocol(), panel(outcomes=(0,) * 4))['metrics']
        positive = evaluate_predictions(protocol(), panel(outcomes=(1,) * 4))['metrics']
        self.assertIsNone(negative['rocAuc'])
        self.assertIsNone(negative['averagePrecision'])
        self.assertIsNone(negative['prAucTrapezoidal'])
        self.assertIsNone(negative['classification'][0]['sensitivity'])
        self.assertIsNone(positive['rocAuc'])
        self.assertEqual(positive['averagePrecision'], 1)
        self.assertIsNone(positive['classification'][0]['specificity'])

    def test_single_subject_has_no_fake_auc(self):
        p = protocol(subjects=['DEMO-ONLY'])
        v = panel(p, probabilities=(.2,), outcomes=(1,))
        m = evaluate_predictions(p, v)['metrics']
        self.assertIsNone(m['rocAuc'])
        self.assertAlmostEqual(m['brier'], .64)

    def test_single_class_folds_do_not_erase_valid_pooled_metrics(self):
        p = protocol(split_type='OOF')
        value = evaluate_predictions(p, panel(p, outcomes=(0, 1, 0, 1)))
        self.assertIsNotNone(value['metrics']['rocAuc'])
        self.assertEqual(len(value['foldMetrics']), 2)
        for fold in value['foldMetrics'].values():
            self.assertIsNone(fold['rocAuc'])
            self.assertEqual(fold['subjects'], 2)

    def test_calibration_bins_empty_bins_boundaries_and_no_fit(self):
        p = dict(protocol(), calibrationBinEdges=[0, .25, .5, .75, 1])
        m = evaluate_predictions(p, panel(p, probabilities=(0, .5, .5, 1)))['metrics']['calibration']
        self.assertEqual([row['count'] for row in m['bins']], [1, 2, 0, 1])
        self.assertIsNone(m['bins'][2]['meanProbability'])
        self.assertIsNone(m['bins'][2]['eventFraction'])
        self.assertIsNone(m['fittedSlope'])
        self.assertIsNone(m['fittedIntercept'])
        self.assertEqual(m['fitReason'], 'NOT_FITTED')

    def test_hand_calculated_fixed_bin_calibration_error(self):
        c = evaluate_predictions(protocol(), panel())['metrics']['calibration']
        self.assertAlmostEqual(c['bins'][0]['meanProbability'], 17 / 60)
        self.assertAlmostEqual(c['bins'][0]['eventFraction'], 1 / 3)
        self.assertAlmostEqual(c['expectedCalibrationError'], .0875)
        self.assertAlmostEqual(c['predictedMinusObserved'], -.0875)

    def test_no_positive_predictions_has_null_ppv_not_zero(self):
        m = evaluate_predictions(protocol(), panel(probabilities=(0,) * 4))['metrics']
        self.assertIsNone(m['classification'][0]['positivePredictiveValue'])

    def test_flags_and_json_are_finite_with_no_execution_or_acceptance(self):
        value = evaluate_predictions(protocol(), panel())
        for key in ('modelExecuted', 'modelFitted', 'predictionProduced', 'recalibrated', 'persisted',
                    'sourceAuthenticityVerified', 'researchAcceptanceEstablished', 'clinicalValidityEstablished'):
            self.assertFalse(value[key])
        json.dumps(value, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
