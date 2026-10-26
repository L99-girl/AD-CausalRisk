"""No optimizer steps: numerical and differential checks against frozen reference."""
import unittest
from unittest.mock import patch
import json
from pathlib import Path
import tempfile
import numpy as np
import pandas as pd
import torch
from torch.nn import functional as F
from research_runtime import graph
from research_runtime.graph_native import (GraphNetwork, GraphHazards, FEATURES, state_digest,
                                          make_graph_estimator, save_graph, load_graph, digest)
from research_runtime.tests.test_graph import parameters


class NativeGraphTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(1)
        self.values = np.tile(np.linspace(.1, 1, 10), (3, 1))
        self.observed = np.ones((3, 10), dtype=bool)
        self.observed[1, 8] = False
        self.values[1, 8] = np.nan

    def network(self, arm='prior'):
        model = GraphNetwork(arm)
        model.import_reference(parameters())
        return model

    def test_all_forward_fields_match_frozen_numpy_reference(self):
        for arm in graph.protocol()[0]['arms']:
            expected = graph.reference_forward(self.values, self.observed, arm, parameters())
            actual = self.network(arm)(torch.tensor(self.values), torch.tensor(self.observed))
            for name in ('encoded', 'states', 'hazards', 'cif'):
                np.testing.assert_allclose(actual[name].detach().numpy(), expected[name], atol=2e-14, rtol=0)
            np.testing.assert_array_equal(actual['allowed_routes'], expected['allowed_routes'])
            for a, b in zip(actual['attention'], expected['attention']):
                np.testing.assert_allclose(a.detach().numpy(), b, atol=2e-14, rtol=0)

    def test_loss_uses_valid_messages_and_masked_logit_message_gradients_are_zero(self):
        result = self.network()(torch.tensor(self.values), torch.tensor(self.observed))
        loss = F.cross_entropy(result['readout'][:, 0], torch.tensor([0, 1, 2]))
        allowed = result['allowed_routes']
        cross = allowed & ~torch.eye(10, dtype=torch.bool)[None]
        gradients = torch.autograd.grad(loss, result['logits'] + result['messages'])
        for grad in gradients[:2]:
            self.assertEqual(torch.count_nonzero(grad[~allowed]).item(), 0)
        for grad in gradients[2:]:
            self.assertEqual(torch.count_nonzero(grad[~allowed]).item(), 0)
            self.assertGreater(grad[cross].abs().max().item(), 0)

    def test_attention_gradient_nonzero_on_nonconstant_valid_logits(self):
        model = self.network()
        with torch.no_grad():
            model.attentions[0][0] = .3
        result = model(torch.tensor(self.values), torch.tensor(self.observed))
        gradient, = torch.autograd.grad(result['readout'][0, 0, 1], (result['logits'][0],))
        self.assertGreater(gradient.abs().max().item(), 0)

    def test_gradcheck_values_with_positive_relu_states(self):
        model = self.network()
        values = torch.tensor(self.values[:1], requires_grad=True)
        observed = torch.tensor(self.observed[:1])
        self.assertTrue(torch.autograd.gradcheck(lambda x: model(x, observed)['readout'][:, 0],
                                                (values,), eps=1e-6, atol=1e-5, rtol=1e-4))

    def test_same_initialization_shapes_and_count_for_three_arms(self):
        models = [GraphNetwork(arm, 20260926) for arm in graph.protocol()[0]['arms']]
        self.assertEqual(len({state_digest(m) for m in models}), 1)
        shapes = [[tuple(p.shape) for p in m.parameters()] for m in models]
        self.assertEqual(shapes[0], shapes[1]); self.assertEqual(shapes[0], shapes[2])
        self.assertEqual(sum(p.numel() for p in models[0].parameters()), 568)

    def test_missing_raw_value_cannot_become_observed_after_transform(self):
        estimator = GraphHazards()
        estimator.medians_ = np.ones(10) * 99
        estimator.mean_ = np.zeros(10); estimator.scale_ = np.ones(10)
        values, observed = estimator._transform(self.values)
        self.assertFalse(observed[1, 8]); self.assertEqual(values[1, 8].item(), 0)
        result = self.network()(values, observed)
        self.assertFalse(result['allowed_routes'][1, 0, 8])

    def test_input_rejections_before_optimizer(self):
        frame = pd.DataFrame(np.ones((3, 10)), columns=FEATURES); frame['month'] = [1, 2, 25]
        with patch('torch.optim.Adam', side_effect=AssertionError('optimizer must not be created')):
            with self.assertRaises(ValueError): GraphHazards().fit(frame, np.array([0, 1, 2]))
            frame['month'] = 1
            with self.assertRaises(ValueError): GraphHazards().fit(frame, np.array([0, 1, 1]))
            with self.assertRaises(ValueError): GraphHazards().fit(frame.iloc[:, ::-1], np.array([0, 1, 2]))

    def test_graph_arm_changes_prediction_and_self_only_attention_has_zero_gradient(self):
        values = torch.tensor(self.values); observed = torch.tensor(self.observed)
        a = self.network('prior')(values, observed)['cif']
        model = self.network('self_only'); result = model(values, observed)
        self.assertGreater((a-result['cif']).abs().max().item(), 0)
        gradient, = torch.autograd.grad(result['readout'].sum(), (model.attentions[0],))
        self.assertEqual(torch.count_nonzero(gradient).item(), 0)

    def test_archive_rejects_protocol_software_feature_source_and_tensor_changes(self):
        # Construct constants, no training or optimizer steps.
        model = make_graph_estimator('prior', 20260926)
        estimator = model.named_steps['hazards']; estimator.network_ = self.network()
        estimator.medians_ = estimator.mean_ = np.zeros(10); estimator.scale_ = np.ones(10)
        estimator.protocol_sha256_ = graph.protocol()[1]; estimator.training_input_sha256_ = 'a'*64
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'constants.npz'
            save_graph(model, path, scope_identity='b'*64)
            with np.load(path, allow_pickle=False) as archive:
                original = {key: archive[key].copy() for key in archive.files}
            for field, value in [('protocol_sha256', '0'*64), ('software', {}),
                                 ('features', list(reversed(FEATURES))), ('source_sha256', '0'*64),
                                 ('clinical_use', True)]:
                arrays = original.copy(); metadata = json.loads(arrays['metadata'].tobytes())
                metadata[field] = value
                arrays['metadata'] = np.frombuffer(json.dumps(metadata).encode(), dtype=np.uint8)
                changed = Path(temp)/f'{field}.npz'; np.savez_compressed(changed, **arrays)
                with self.assertRaises(ValueError):
                    load_graph(changed, digest(changed), expected_arm='prior',
                               expected_training_input_sha256='a'*64, expected_scope_identity='b'*64)
            for value in (np.zeros((1, 3)), np.full((104, 3), np.nan)):
                arrays = original.copy(); arrays['head'] = value
                changed = Path(temp)/f'tensor-{value.shape[0]}.npz'; np.savez_compressed(changed, **arrays)
                with self.assertRaises(ValueError):
                    load_graph(changed, digest(changed), expected_arm='prior',
                               expected_training_input_sha256='a'*64, expected_scope_identity='b'*64)


if __name__ == '__main__':
    unittest.main()
