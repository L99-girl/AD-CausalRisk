"""Constant neural parameters only; no optimization or clinical/model file reads."""
from copy import deepcopy
import unittest
import numpy as np
import torch
from research_runtime import graph_explanation as explain
from research_runtime.graph_native import make_graph_estimator, FEATURES
from research_runtime.training import synthetic_cohort, checked_design, prediction_hash
from research_runtime.discrete import person_period
from research_runtime.tests.test_graph_training import constant_fit


class ExplanationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        cls.frame, cls.splits, _ = checked_design(synthetic_cohort(), 'multimodal_values')
        cls.models = {}; raw = {(seed, arm):np.zeros((90, 2)) for seed in (20260926, 20260927, 20260928)
                                for arm in ('self_only', 'prior', 'semantic_permutation')}
        weights = np.zeros(90)
        for fold, (a, b) in enumerate(cls.splits, 1):
            periods, labels = person_period(cls.frame.iloc[a], list(FEATURES))
            weights[b] = explain.horizon_ipcw_weights(cls.frame.iloc[b], explain.censor_survival(cls.frame.iloc[a]))
            for seed, arm in raw:
                model = make_graph_estimator(arm, seed)
                constant_fit(model.named_steps['hazards'], periods, labels)  # Assign constants, never invoke fit.
                cls.models[fold, seed, arm] = model
                raw[seed, arm][b] = explain.checked_cif(model, cls.frame.iloc[b])
        cls.expected = dict(models=[])
        for arm in ('self_only', 'prior', 'semantic_permutation'):
            mean = np.stack([raw[seed, arm] for seed in (20260926, 20260927, 20260928)]).mean(0)
            cls.expected['models'].append(dict(arm=arm, ad_oof_sha256=prediction_hash(mean[:, 0]),
                other_oof_sha256=prediction_hash(mean[:, 1]),
                pooled_oof_brier=float(np.mean(weights*(cls.frame.event_type.eq(1).to_numpy(float)-mean[:, 0])**2)),
                per_seed=[dict(seed=seed, ad_oof_sha256=prediction_hash(raw[seed, arm][:, 0]),
                               other_oof_sha256=prediction_hash(raw[seed, arm][:, 1])) for seed in (20260926, 20260927, 20260928)]))

    def test_full_matrix_counts_and_aggregate_only_result(self):
        loader = lambda arm, seed, fold:self.models[fold, seed, arm]
        result = explain.evaluate(self.frame, self.splits, loader, self.expected)
        self.assertEqual((result['existing_model_loads'], result['cif_calls'], result['native_numpy_trace_pairs']), (45, 1230, 45))
        self.assertEqual(result['fits'], 0); self.assertLessEqual(result['cif_reconstruction_max_error'], 1e-12)
        self.assertLessEqual(result['trace_reconstruction_max_error'], 1e-12)
        self.assertEqual(len(result['importance']), 6)
        self.assertEqual([len(row['edges']) for row in result['route_sensitivity']], [0, 11, 11])
        self.assertEqual(result['route_sensitivity'][0]['all_cross_routes_removed_mean_abs_ad'], 0)
        import json
        self.assertNotIn('SYNTHETIC-000', json.dumps(result))
        self.assertFalse(result['participant_explanations_saved'])

    def test_baseline_mismatch_stops_before_explanation(self):
        expected = deepcopy(self.expected); expected['models'][0]['per_seed'][0]['other_oof_sha256'] = '0'*64
        events = []
        with self.assertRaisesRegex(ValueError, 'SEED_OOF_CHANGED'):
            explain.evaluate(self.frame, self.splits, lambda arm, seed, fold:self.models[fold, seed, arm], expected, events.append)
        self.assertEqual(events, [])

    def test_telescoping_both_causes_preserves_missing_groups_and_model(self):
        frame = self.frame.iloc[self.splits[0][1]]; model = self.models[1, 20260926, 'prior']
        before = explain.model_identity(model); calls = explain.Calls(17)
        baseline = explain.checked_cif(model, frame)
        reference, values, error = explain.telescoping(model, frame, baseline, calls)
        self.assertEqual(calls.count, 17); self.assertLessEqual(error, 1e-12)
        self.assertEqual(before, explain.model_identity(model))
        for contributions in values.values():
            np.testing.assert_allclose(reference+contributions.sum(1), baseline, atol=1e-12, rtol=0)
            self.assertTrue((contributions[~explain.observation_groups(frame)] == 0).all())

    def test_canonical_and_reverse_can_differ_despite_exact_additivity(self):
        class Model:pass
        model = Model(); model.named_steps = {'hazards':Model()}; model.named_steps['hazards'].medians_ = np.zeros(10)
        frame = self.frame.iloc[:2].copy(); frame.loc[:, list(FEATURES)] = 1.
        def interaction(_, values):
            score = values.age_years.to_numpy()*values.education_years.to_numpy()*.1
            return np.c_[score, score*.2]
        baseline = interaction(model, frame)
        reference, values, error = explain.telescoping(model, frame, baseline, interaction)
        self.assertEqual(error, 0)
        self.assertGreater(np.abs(values['forward']-values['reverse']).max(), 0)

    def test_route_deletion_changes_only_diagnostic_copy(self):
        original = self.models[1, 20260926, 'prior']; before = explain.model_identity(original)
        edges = tuple(original.named_steps['hazards'].network_.edges)
        changed = explain.without_routes(original, edges)
        self.assertEqual(changed.named_steps['hazards'].network_.edges, ())
        self.assertEqual(explain.model_identity(original), before)
        self.assertNotEqual(explain.model_identity(changed), before)
        with self.assertRaises(ValueError):explain.without_routes(original, ((9, 0),))

    def test_trace_rejects_graph_other_than_the_actual_model_arm(self):
        model = deepcopy(self.models[1, 20260926, 'prior']); model.named_steps['hazards'].network_.edges = ()
        frame = self.frame.iloc[self.splits[0][1]]
        with self.assertRaisesRegex(ValueError, 'DISPLAY_GRAPH'):
            explain.trace(model, frame, explain.checked_cif(model, frame))

    def test_group_and_reference_validation(self):
        frame = self.frame.iloc[:3].copy(); frame.loc[frame.index[0], FEATURES[8]] = np.nan
        frame.loc[frame.index[0], FEATURES[9]] = 5
        with self.assertRaises(ValueError):explain.observation_groups(frame)
        with self.assertRaises(ValueError):explain.median_reference(frame, np.full(10, np.nan))

    def test_budget_and_undefined_rank(self):
        calls = explain.Calls(0)
        with self.assertRaisesRegex(ValueError, 'BUDGET'):calls(self.models[1, 20260926, 'prior'], self.frame.iloc[:1])
        self.assertIsNone(explain.rank(np.ones(3), np.arange(3)))
        result = explain.local_rank_summary(np.zeros((2, 9)), np.zeros((2, 9)), np.zeros((2, 9), bool))
        self.assertEqual(result['insufficient_observed_groups'], 2); self.assertEqual(result['spearman']['n'], 0)


if __name__ == '__main__':unittest.main()
