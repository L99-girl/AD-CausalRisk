"""Graph orchestration checks: constant parameter fixtures, zero optimizer fits."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from research_runtime import graph_training as runner
from research_runtime.graph_native import GraphHazards, GraphNetwork, FEATURES, state_digest
from research_runtime.training import synthetic_cohort, checked_design, Journal


def constant_fit(self, X, y):
    values = X[list(FEATURES)].to_numpy(float)
    self.medians_ = np.nan_to_num(np.nanmedian(values, axis=0), nan=0)
    filled = np.where(np.isnan(values), self.medians_, values)
    self.mean_ = filled.mean(0); self.scale_ = filled.std(0); self.scale_[self.scale_ == 0] = 1
    self.network_ = GraphNetwork(self.arm, self.seed)
    self.initial_state_sha256_ = state_digest(self.network_)
    self.batch_schedule_sha256_ = 'constant-fixture-batches'
    self.training_input_sha256_ = 'a'*64
    self.protocol_sha256_ = runner.protocol()[1]
    self.classes_ = np.array([0, 1, 2]); self.loss_history_ = [1.]*40; self.fit_seconds_ = .001
    return self


class GraphTrainingTests(unittest.TestCase):
    def setUp(self):
        import torch
        torch.set_num_threads(1)
        self.frame, self.splits, _ = checked_design(synthetic_cohort(), 'multimodal_values')

    def test_constant_model_full_orchestration_54_calls_no_optimization(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(GraphHazards, 'fit', autospec=True, side_effect=constant_fit) as fit:
            with contextlib.redirect_stdout(io.StringIO()):
                result = runner.run_graph_comparison(self.frame, Path(temp)/'new', splits=self.splits,
                    input_bindings={'source':'ARTIFICIAL_CONSTANT_FIXTURE'}, research_scope='CONSTRUCTED_NO_OPTIMIZATION')
            self.assertEqual(fit.call_count, 54)
            self.assertEqual(result['fits'], dict(predictive=54, calibration=0))
            self.assertEqual(result['saved_model_replay_max_abs_error'], 0)
            self.assertEqual(len(result['models']), 3); self.assertEqual(len(result['contrasts']), 2)
            manifest = json.loads((Path(temp)/'new/Model_Manifest.json').read_text())
            self.assertEqual(sum(row['role']=='GRAPH_OUTER_VALIDATION' for row in manifest['models']), 45)
            self.assertEqual(sum(row['role']=='GRAPH_FINAL' for row in manifest['models']), 9)
            self.assertFalse(list((Path(temp)/'new').glob('*prediction*')))
            expected = [(fold, seed, arm) for fold in range(1, 6) for seed in runner.protocol()[0]['future_initialization_seeds']
                        for arm in runner.protocol()[0]['arms']]
            actual = [(row['outer_fold'], row['seed'], row['arm']) for row in manifest['models'][:45]]
            self.assertEqual(actual, expected)

    def test_leaking_fold_rejected_before_model_or_output(self):
        folds = list(self.splits); a, b = folds[0]; folds[0] = (np.r_[a, b[0]], b)
        with tempfile.TemporaryDirectory() as temp, patch.object(GraphHazards, 'fit') as fit:
            output = Path(temp)/'must-not-exist'
            with self.assertRaises(ValueError):
                runner.run_graph_comparison(self.frame, output, splits=folds, input_bindings={}, research_scope='FIXTURE')
            fit.assert_not_called(); self.assertFalse(output.exists())

    def test_predictive_budget_cannot_exceed_54_and_calibration_forbidden(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = runner.GraphJournal(Path(temp))
            try:
                with self.assertRaises(ValueError): ledger.attempt('calibration')
                for _ in range(54): ledger.attempt('predictive')
                with self.assertRaises(ValueError): ledger.attempt('predictive')
            finally: ledger.close()

    def test_interval_uses_frozen_10000_draws_and_97_5_quantiles(self):
        values = np.array([-.2, -.1, .05, .3])
        rng = np.random.default_rng(20260926)
        samples = rng.integers(0, len(values), (10000, len(values)))
        expected = np.quantile(values[samples].mean(1), [.0125, .9875])
        np.testing.assert_array_equal(runner.conditional_interval(values), expected)
        with self.assertRaises(ValueError): runner.conditional_interval([np.nan, 0])

    def test_summary_averages_cif_before_squared_error(self):
        values = {}; seeds = runner.protocol()[0]['future_initialization_seeds']
        for seed, probability in zip(seeds, (.1, .3, .5)):
            for arm in runner.protocol()[0]['arms']:
                values[seed, arm] = np.tile([probability, .01], (len(self.frame), 1))
        result = runner.summarize(self.frame, self.splits, values)
        weights = np.zeros(len(self.frame))
        for a, b in self.splits:
            weights[b] = runner.horizon_ipcw_weights(self.frame.iloc[b], runner.censor_survival(self.frame.iloc[a]))
        expected = float(np.mean(weights*(self.frame.event_type.eq(1).to_numpy(float)-.3)**2))
        self.assertAlmostEqual(result['models'][0]['pooled_oof_brier'], expected, places=14)
        self.assertFalse(result['fixed_internal_prior_increment_supported'])
        for row in result['contrasts']:
            self.assertEqual(row['brier_difference'], 0); self.assertEqual(row['conditional_97_5_interval'], [0, 0])

    def test_incomplete_oof_rejected(self):
        values = {(seed, arm):np.full((len(self.frame), 2), np.nan)
                  for seed in runner.protocol()[0]['future_initialization_seeds'] for arm in runner.protocol()[0]['arms']}
        with self.assertRaises(ValueError): runner.summarize(self.frame, self.splits, values)

    def test_failed_fit_stops_and_records_attempt_no_retry(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(GraphHazards, 'fit', side_effect=ValueError('INJECTED')) as fit:
            output = Path(temp)/'new'
            with self.assertRaisesRegex(ValueError, 'INJECTED'):
                runner.run_graph_comparison(self.frame, output, splits=self.splits, input_bindings={}, research_scope='FIXTURE')
            self.assertEqual(fit.call_count, 1)
            state = json.loads((output/'Run_State.json').read_text())
            self.assertEqual(state['status'], 'FAILED'); self.assertEqual(state['attempted_fits']['predictive'], 1)


if __name__ == '__main__': unittest.main()
