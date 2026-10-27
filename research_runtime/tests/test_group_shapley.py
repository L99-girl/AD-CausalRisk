"""Analytic games and constant graph parameters; no optimization/file models."""
from itertools import permutations
import unittest

import numpy as np

from research_runtime.group_shapley import exact_values, explain_graph


class GroupShapleyTests(unittest.TestCase):
    @staticmethod
    def groups(n):
        return tuple((str(i), (i,)) for i in range(n))

    def test_interaction_has_known_symmetric_attribution_for_both_causes(self):
        def predict(x):
            y = .1 + .1*x[:, 0] + .1*x[:, 1] + .2*x[:, 0]*x[:, 1]
            return np.c_[y, y/4]
        result = exact_values(predict, np.ones((1, 2)), np.zeros((1, 2)), self.groups(2))
        np.testing.assert_allclose(result['contributions'][0], [[.2, .05], [.2, .05]], atol=1e-15)
        self.assertEqual(result['coalition_evaluations'], 4)
        self.assertFalse(result['is_causal_effect'])

    def test_independent_permutation_average_oracle_and_group_reordering(self):
        x = np.array([[1., .8, .7, .5], [.2, .3, .4, .9]])
        ref = np.full_like(x, .1)
        def predict(a):
            y = .05 + .1*a[:, 0]*a[:, 1] + .2*a[:, 1]*a[:, 2]*a[:, 3] + .1*a[:, 3]
            return np.c_[y, .3-y/3]
        expected = np.zeros((2, 4, 2))
        for order in permutations(range(4)):
            state = ref.copy(); previous = predict(state)
            for i in order:
                state[:, i] = x[:, i]; current = predict(state)
                expected[:, i] += (current-previous)/24
                previous = current
        result = exact_values(predict, x, ref, self.groups(4))
        reverse = exact_values(predict, x, ref, tuple(reversed(self.groups(4))))
        np.testing.assert_allclose(result['contributions'], expected, atol=1e-15, rtol=0)
        np.testing.assert_allclose(reverse['contributions'][:, ::-1], expected, atol=1e-15, rtol=0)

    def test_missingness_and_unchanged_groups_are_exact_dummy_players(self):
        x = np.array([[1., np.nan, 4.], [np.nan, 2., 4.]])
        ref = np.array([[0., np.nan, 4.], [np.nan, 0., 4.]])
        result = exact_values(lambda a: np.c_[np.nansum(a[:, :2], axis=1)/10, np.zeros(2)],
                              x, ref, self.groups(3))
        self.assertEqual(result['coalition_evaluations'], 4)
        np.testing.assert_array_equal(result['contributions'][0, 1:], 0)
        np.testing.assert_array_equal(result['contributions'][1, [0, 2]], 0)
        np.testing.assert_allclose(result['contributions'][:, :, 0], [[.1, 0, 0], [0, .2, 0]])

    def test_group_partition_keeps_bilateral_columns_together(self):
        result = exact_values(lambda a: np.c_[a[:, 0]*a[:, 1]/10, np.zeros(len(a))],
                              np.array([[2., 3.]]), np.zeros((1, 2)), (('bilateral', (0, 1)),))
        np.testing.assert_allclose(result['contributions'][0, 0], [.6, 0])
        self.assertEqual(result['coalition_evaluations'], 2)

    def test_reference_changes_allocation_without_changing_prediction(self):
        predict = lambda a: np.c_[a[:, 0]*a[:, 1]/4, np.zeros(len(a))]
        a = exact_values(predict, np.ones((1, 2)), np.zeros((1, 2)), self.groups(2))
        b = exact_values(predict, np.ones((1, 2)), np.array([[1., 0.]]), self.groups(2))
        np.testing.assert_array_equal(a['prediction_cif'], b['prediction_cif'])
        self.assertGreater(np.abs(a['contributions']-b['contributions']).max(), .1)

    def test_full_nine_group_game_and_zero_active_group_game(self):
        def predict(a):
            y = a.sum(axis=1)/100
            return np.c_[y, y/2]
        x = np.ones((1, 9)); ref = np.zeros_like(x)
        result = exact_values(predict, x, ref, self.groups(9))
        self.assertEqual(result['coalition_evaluations'], 512)
        np.testing.assert_allclose(result['contributions'][0], [[.01, .005]]*9, atol=1e-15)
        same = exact_values(predict, x, x, self.groups(9))
        self.assertEqual(same['coalition_evaluations'], 1)
        np.testing.assert_array_equal(same['contributions'], 0)

    def test_budget_and_invalid_inputs_rejected_before_prediction(self):
        calls = []
        predict = lambda a: calls.append(a)
        cases = [
            (np.ones((1, 2)), np.zeros((1, 2)), self.groups(2), {'max_coalitions': 3}),
            (np.ones((1, 2)), np.zeros((1, 2)), (('a', (0,)), ('b', (0,))), {}),
            (np.ones((1, 2)), np.array([[0., np.nan]]), self.groups(2), {}),
            (np.ones((257, 2)), np.zeros((257, 2)), self.groups(2), {}),
            (np.ones((1, 2)), np.zeros((1, 2)), self.groups(2), {'max_coalitions': True}),
            (np.array([[np.inf, 1.]]), np.zeros((1, 2)), self.groups(2), {}),
        ]
        for x, ref, groups, kwargs in cases:
            with self.subTest(shape=x.shape, kwargs=kwargs):
                with self.assertRaises(ValueError): exact_values(predict, x, ref, groups, **kwargs)
        self.assertEqual(calls, [])

    def test_mutation_invalid_outputs_and_reused_output_buffer(self):
        x = np.ones((1, 2)); ref = np.zeros_like(x)
        def mutate(a):
            a.flags.writeable = True; a[0, 0] = 9
            return np.zeros((1, 2))
        with self.assertRaisesRegex(ValueError, 'MUTATED'):
            exact_values(mutate, x, ref, self.groups(2))
        for invalid in (np.ones((1, 2)), np.array([[np.nan, 0.]]), np.zeros((1, 1)),
                        np.array([[False, False]]), np.array([[-.1, .2]])):
            with self.assertRaisesRegex(ValueError, 'TWO_CAUSE'):
                exact_values(lambda a: invalid, x, ref, self.groups(2))
        shared = np.zeros((1, 2))
        def predict(a):
            shared[0] = [a.sum()/10, 0.]; return shared
        result = exact_values(predict, x, ref, self.groups(2))
        np.testing.assert_allclose(result['contributions'][0, :, 0], [.1, .1])
        np.testing.assert_array_equal(x, 1)
        np.testing.assert_array_equal(ref, 0)

    def test_existing_graph_cif_adapter_with_constant_parameters_and_fold_reference(self):
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
        constant_fit(model.named_steps['hazards'], periods, labels)  # No optimizer/fit call.
        current = frame.iloc[test[:2]].copy()
        medians = model.named_steps['hazards'].medians_
        for i, col in enumerate(FEATURES): current.loc[:, col] = medians[i]
        current.loc[:, FEATURES[0]] += 1
        current.loc[:, FEATURES[1]] += 1
        before = current.copy(deep=True); identity = model_identity(model)
        result = explain_graph(model, current, max_coalitions=4)
        self.assertEqual((result['coalition_evaluations'], result['cif_calls'], result['fits']), (4, 4, 0))
        self.assertEqual(result['model_identity'], identity)
        self.assertEqual(model_identity(model), identity)
        self.assertTrue(current.equals(before))
        np.testing.assert_allclose(result['reference_cif']+result['contributions'].sum(axis=1),
                                   result['prediction_cif'], atol=1e-12, rtol=0)
        current.loc[current.index[0], FEATURES[8]] = np.nan
        with self.assertRaisesRegex(ValueError, 'PARTIAL_EXPLANATION_GROUP'):
            explain_graph(model, current)


if __name__ == '__main__':
    unittest.main()
