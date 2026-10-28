"""Analytic local-surrogate checks; local regressions are counted separately."""
import unittest

import numpy as np

from research_runtime.group_lime import local_surrogate, explain_graph


class GroupLimeTests(unittest.TestCase):
    @staticmethod
    def groups(n):
        return tuple((str(i), (i,)) for i in range(n))

    def test_linear_game_has_known_slopes_for_both_causes(self):
        predict = lambda a: np.c_[.1+a[:, 0]*.2+a[:, 1]*.1, .2-a[:, 0]*.05]
        result = local_surrogate(predict, np.ones((1, 2)), np.zeros((1, 2)),
                                 self.groups(2), ridge=1e-12)
        np.testing.assert_allclose(result['contributions'][0], [[.2, -.05], [.1, 0]], atol=1e-11)
        np.testing.assert_allclose(result['surrogate_intercept'], [[.1, .2]], atol=1e-11)
        self.assertEqual(result['local_surrogate_fits'], 1)
        self.assertTrue(all(v > .999999 for v in result['weighted_r2']))

    def test_nonlinear_game_reports_fidelity_residual_instead_of_redistributing_it(self):
        predict = lambda a: np.c_[.1+.4*a[:, 0]*a[:, 1], np.full(len(a), .1)]
        result = local_surrogate(predict, np.ones((1, 2)), np.zeros((1, 2)), self.groups(2))
        self.assertGreater(abs(result['observed_residual'][0, 0]), .01)
        self.assertGreater(result['weighted_rmse'][0], .01)
        self.assertIsNone(result['weighted_r2'][1])
        np.testing.assert_allclose(result['surrogate_intercept']+result['contributions'].sum(axis=1)
                                   +result['observed_residual'], result['prediction_cif'], atol=1e-15)
        self.assertFalse(result['is_causal_effect'])

    def test_fixed_seed_replays_and_other_seed_can_change_neighborhood_and_coefficients(self):
        def predict(a):
            y = .05+.4*np.prod(a, axis=1)
            return np.c_[y, np.full(len(a), .1)]
        def run(seed):
            return local_surrogate(predict, np.ones((1, 5)), np.zeros((1, 5)), self.groups(5),
                                   samples=10, seed=seed)
        a, b, c = run(1), run(1), run(2)
        self.assertEqual(a['mask_sha256'], b['mask_sha256'])
        np.testing.assert_array_equal(a['contributions'], b['contributions'])
        self.assertNotEqual(a['mask_sha256'], c['mask_sha256'])
        self.assertGreater(np.abs(a['contributions']-c['contributions']).max(), 1e-5)

    def test_reference_and_kernel_sensitivity_remain_visible(self):
        predict = lambda a: np.c_[a[:, 0]*a[:, 1]/4, np.zeros(len(a))]
        args = (predict, np.ones((1, 2)), np.zeros((1, 2)), self.groups(2))
        base = local_surrogate(*args)
        narrow = local_surrogate(*args, kernel_width=.3)
        changed = local_surrogate(predict, args[1], np.array([[1., 0.]]), self.groups(2))
        self.assertGreater(np.abs(base['contributions']-narrow['contributions']).max(), .01)
        self.assertGreater(np.abs(base['contributions']-changed['contributions']).max(), .01)
        np.testing.assert_array_equal(base['prediction_cif'], changed['prediction_cif'])

    def test_missing_joint_group_and_zero_active_game(self):
        x = np.array([[1., np.nan, np.nan]])
        ref = np.array([[0., np.nan, np.nan]])
        predict = lambda a: np.c_[a[:, 0]/10, np.full(len(a), .1)]
        groups = (('one', (0,)), ('bilateral', (1, 2)))
        result = local_surrogate(predict, x, ref, groups)
        np.testing.assert_array_equal(result['contributions'][:, 1], 0)
        same = local_surrogate(predict, x, x, groups)
        self.assertEqual((same['neighborhood_evaluations'], same['local_surrogate_fits']), (1, 0))
        self.assertEqual(same['weighted_r2'], [None, None])

    def test_rejects_budget_bad_configuration_and_multisubject_before_prediction(self):
        calls = []
        predict = lambda a: calls.append(a)
        x = np.ones((1, 3)); ref = np.zeros_like(x)
        for kwargs in ({'max_evaluations': 2}, {'samples': 2}, {'seed': True},
                       {'ridge': 0}, {'kernel_width': float('nan')}, {'kernel_width': 1e-100}):
            with self.assertRaises(ValueError):
                local_surrogate(predict, x, ref, self.groups(3), **kwargs)
        with self.assertRaisesRegex(ValueError, 'ONE_SUBJECT'):
            local_surrogate(predict, np.ones((2, 3)), np.zeros((2, 3)), self.groups(3))
        self.assertEqual(calls, [])

    def test_graph_adapter_preserves_actual_model_and_input(self):
        import torch
        from research_runtime.graph_native import make_graph_estimator, FEATURES
        from research_runtime.training import synthetic_cohort, checked_design
        from research_runtime.discrete import person_period
        from research_runtime.tests.test_graph_training import constant_fit
        from research_runtime.graph_explanation import model_identity
        torch.set_num_threads(1)
        frame, splits, _ = checked_design(synthetic_cohort(), 'multimodal_values')
        train, test = splits[0]
        periods, labels = person_period(frame.iloc[train], list(FEATURES))
        model = make_graph_estimator('prior', 20260926)
        constant_fit(model.named_steps['hazards'], periods, labels)
        current = frame.iloc[test[:1]].copy()
        for i, col in enumerate(FEATURES): current.loc[:, col] = model.named_steps['hazards'].medians_[i]
        current.loc[:, FEATURES[0]] += 1
        current.loc[:, FEATURES[1]] += 1
        before = current.copy(deep=True); identity = model_identity(model)
        result = explain_graph(model, current, max_evaluations=4)
        self.assertEqual((result['cif_calls'], result['local_surrogate_fits']), (4, 1))
        self.assertEqual(result['model_identity'], identity)
        self.assertEqual(model_identity(model), identity)
        self.assertTrue(current.equals(before))


if __name__ == '__main__':
    unittest.main()
