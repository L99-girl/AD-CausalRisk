"""Constructed integer/nullable-integer input regression; no source readers."""
import unittest
from types import SimpleNamespace

import numpy as np
import pandas as pd

from research_runtime import group_lime, group_shapley
from research_runtime.graph_native import FEATURES


class ReplacementDtypeTests(unittest.TestCase):
    def test_fractional_reference_preserves_nullable_masks_and_caller_dtypes(self):
        frame = pd.DataFrame({name: pd.Series([10, pd.NA], dtype='Int64') for name in FEATURES})
        frame['source_note'] = ['CONSTRUCTED', 'CONSTRUCTED']
        before = frame.copy(deep=True)
        model = SimpleNamespace(named_steps={'hazards': SimpleNamespace(
            medians_=np.arange(10, dtype=float)+.5, mean_=np.arange(10, dtype=float)+.25)})
        for kind, offset in (('median', .5), ('mean', .25)):
            result = group_shapley.graph_reference(model, frame, kind)
            np.testing.assert_array_equal(result.loc[0, list(FEATURES)].to_numpy(), np.arange(10)+offset)
            self.assertTrue(result.loc[1, list(FEATURES)].isna().all())
            self.assertTrue(result.source_note.equals(before.source_note))
        pd.testing.assert_frame_equal(frame, before)

    @staticmethod
    def fixture():
        import torch
        from research_runtime.graph_native import make_graph_estimator
        from research_runtime.training import synthetic_cohort, checked_design
        from research_runtime.discrete import person_period
        from research_runtime.tests.test_graph_training import constant_fit
        torch.set_num_threads(1)
        frame, splits, _ = checked_design(synthetic_cohort(), 'multimodal_values')
        train, test = splits[0]
        periods, labels = person_period(frame.iloc[train], list(FEATURES))
        model = make_graph_estimator('prior', 20260926)
        constant_fit(model.named_steps['hazards'], periods, labels)
        e = model.named_steps['hazards']
        e.medians_ = np.arange(10, dtype=float)+10
        e.mean_ = e.medians_.copy(); e.mean_[:3] += .25
        current = frame.iloc[test[:2]].copy()
        for i, name in enumerate(FEATURES): current[name] = np.full(2, e.medians_[i])
        current[FEATURES[0]] = pd.Series([11, 12], index=current.index, dtype='int64')
        current[FEATURES[1]] = pd.Series([12, 13], index=current.index, dtype='Int64')
        current[FEATURES[2]] = pd.Series([13, pd.NA], index=current.index, dtype='Int64')
        return model, current

    def test_exact_graph_integer_and_float_games_agree_without_mutation(self):
        from research_runtime.graph_explanation import model_identity
        model, frame = self.fixture(); before = frame.copy(deep=True); identity = model_identity(model)
        floating = frame.astype({name: 'float64' for name in FEATURES})
        for kind in ('median', 'mean'):
            result = group_shapley.explain_graph(model, frame, reference_kind=kind, max_coalitions=8)
            expected = group_shapley.explain_graph(model, floating, reference_kind=kind, max_coalitions=8)
            self.assertEqual(result['cif_calls'], 8)
            for key in ('contributions', 'prediction_cif', 'reference_cif'):
                np.testing.assert_array_equal(result[key], expected[key])
            self.assertTrue((result['contributions'][1, 2] == 0).all())
        pd.testing.assert_frame_equal(frame, before); self.assertEqual(model_identity(model), identity)

    def test_serial_and_batched_lime_integer_columns_match_float_game(self):
        from research_runtime.graph_explanation import model_identity
        model, current = self.fixture(); current = current.iloc[:1].copy()
        before = current.copy(deep=True); identity = model_identity(model)
        floating = current.astype({name: 'float64' for name in FEATURES})
        for kind in ('median', 'mean'):
            opts = dict(reference_kind=kind, samples=4, holdout_samples=4)
            serial = group_lime.explain_graph(model, current, **opts)
            batch = group_lime.explain_graph(model, current, batch_predictions=True, **opts)
            expected = group_lime.explain_graph(model, floating, batch_predictions=True, **opts)
            self.assertEqual((serial['cif_calls'], batch['cif_calls']), (8, 2))
            for other in (batch, expected):
                self.assertEqual(serial['mask_sha256'], other['mask_sha256'])
                for key in ('contributions', 'prediction_cif', 'reference_cif', 'observed_residual'):
                    np.testing.assert_allclose(serial[key], other[key], atol=1e-12, rtol=0)
        pd.testing.assert_frame_equal(current, before); self.assertEqual(model_identity(model), identity)


if __name__ == '__main__':
    unittest.main()
