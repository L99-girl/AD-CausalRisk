"""Batch equivalence and training-only reference checks, constructed only."""
import unittest

import numpy as np

from research_runtime.group_lime import local_surrogate
from research_runtime.group_shapley import graph_reference


class AdmissionTests(unittest.TestCase):
    def test_fidelity_holdout_masks_are_disjoint_and_do_not_refit_the_surrogate(self):
        calls = []
        def predict(a):
            calls.append(a.copy())
            return np.c_[.1 + .4*np.prod(a, axis=1), np.full(len(a), .1)]
        result = local_surrogate(predict, np.ones((1, 3)), np.zeros((1, 3)),
                                 tuple((str(i), (i,)) for i in range(3)), samples=4,
                                 seed=5, batch_predict=predict, holdout_samples=4)
        self.assertEqual([len(x) for x in calls], [4, 4])
        train_codes = set(map(tuple, calls[0])); test_codes = set(map(tuple, calls[1]))
        self.assertFalse(train_codes & test_codes)
        self.assertEqual(len(train_codes | test_codes), 8)
        self.assertEqual(result['local_surrogate_fits'], 1)
        self.assertEqual(result['heldout_fidelity']['samples'], 4)
        self.assertGreater(result['heldout_fidelity']['weighted_rmse'][0], .01)
        self.assertIsNone(result['heldout_fidelity']['weighted_r2'][1])
        before = len(calls)
        with self.assertRaisesRegex(ValueError, 'BUDGET_EXCEEDED'):
            local_surrogate(predict, np.ones((1, 3)), np.zeros((1, 3)),
                            tuple((str(i), (i,)) for i in range(3)), samples=4,
                            seed=5, batch_predict=predict, holdout_samples=4, max_evaluations=7)
        self.assertEqual(len(calls), before)

    def test_batched_neighborhood_preserves_masks_weights_and_both_output_fits(self):
        calls = []
        def predict(a):
            calls.append(len(a))
            score = .05 + .3*np.prod(a, axis=1)
            return np.c_[score, .2-score/3]
        args = (predict, np.ones((1, 5)), np.zeros((1, 5)), tuple((str(i), (i,)) for i in range(5)))
        serial = local_surrogate(*args, samples=16)
        self.assertEqual(calls, [1]*16)
        calls.clear()
        batch = local_surrogate(*args, samples=16, batch_predict=predict)
        self.assertEqual(calls, [16])
        self.assertEqual(serial['mask_sha256'], batch['mask_sha256'])
        for key in ('contributions', 'surrogate_intercept', 'observed_residual', 'weighted_rmse', 'weighted_r2'):
            np.testing.assert_array_equal(serial[key], batch[key])

    def test_batch_callback_cannot_mutate_states_or_return_invalid_probabilities(self):
        args = (lambda a: np.zeros((len(a), 2)), np.ones((1, 2)), np.zeros((1, 2)), (('a', (0,)), ('b', (1,))))
        def mutate(a):
            a.flags.writeable = True; a[0, 0] = 9
            return np.zeros((len(a), 2))
        with self.assertRaisesRegex(ValueError, 'MUTATED'):
            local_surrogate(*args, batch_predict=mutate)
        with self.assertRaisesRegex(ValueError, 'TWO_CAUSE'):
            local_surrogate(*args, batch_predict=lambda a: np.ones((len(a), 2)))

    def test_actual_graph_batch_matches_serial_for_both_saved_training_references(self):
        import torch
        from research_runtime import group_lime
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
        for i, col in enumerate(FEATURES): current.loc[:, col] = model.named_steps['hazards'].medians_[i]+1
        identity = model_identity(model); snapshot = current.copy(deep=True)
        for kind in ('median', 'mean'):
            serial = group_lime.explain_graph(model, current, samples=16, reference_kind=kind)
            batch = group_lime.explain_graph(model, current, samples=16, reference_kind=kind, batch_predictions=True)
            self.assertEqual((serial['cif_calls'], batch['cif_calls']), (16, 1))
            self.assertEqual(serial['mask_sha256'], batch['mask_sha256'])
            for key in ('contributions', 'reference_cif', 'prediction_cif', 'observed_residual'):
                np.testing.assert_allclose(serial[key], batch[key], atol=1e-12, rtol=0)
        self.assertEqual(model_identity(model), identity)
        self.assertTrue(current.equals(snapshot))

    def test_reference_uses_saved_raw_scale_training_statistics_and_preserves_missingness(self):
        import pandas as pd
        from types import SimpleNamespace
        from research_runtime.graph_native import FEATURES
        model = SimpleNamespace(named_steps={'hazards': SimpleNamespace(
            medians_=np.arange(10, dtype=float), mean_=np.arange(10, dtype=float)+100)})
        frame = pd.DataFrame(np.ones((2, 10)), columns=FEATURES)
        frame.loc[0, FEATURES[2]] = np.nan
        mean = graph_reference(model, frame, 'mean')
        self.assertTrue(np.isnan(mean.loc[0, FEATURES[2]]))
        np.testing.assert_array_equal(mean.iloc[1].to_numpy(), np.arange(10)+100)
        np.testing.assert_array_equal(graph_reference(model, frame).iloc[1].to_numpy(), np.arange(10))
        with self.assertRaisesRegex(ValueError, 'REFERENCE_KIND'):
            graph_reference(model, frame, 'held_out_mean')


if __name__ == '__main__':
    unittest.main()
