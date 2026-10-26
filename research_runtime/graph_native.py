"""CPU differentiable implementation of the frozen graph numerical reference.

In-memory estimator only: no cohort reader, real-training CLI or deployment.
Preprocessing is fitted on the supplied training person-months. Missingness is
captured before imputation and gates cross routes, never the self route.
"""
from __future__ import annotations
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import time

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .graph import protocol, arm_edges, allowed_routes

FEATURES = tuple(protocol()[0]['features'])
PACKAGES = ('numpy', 'pandas', 'scikit-learn', 'scipy', 'torch')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class GraphNetwork(nn.Module):
    """Ten nodes, two single-head layers, source-normalized attention."""
    def __init__(self, arm='prior', seed=20260926):
        super().__init__()
        self.edges = arm_edges(arm)
        self.arm = arm
        self.protocol_sha256 = protocol()[1]
        generator = torch.Generator(device='cpu').manual_seed(seed)
        def parameter(shape, offset=0):
            return nn.Parameter(torch.randn(shape, generator=generator, dtype=torch.float64) * .05 + offset)
        self.input_projection = parameter((2, 8))
        self.node_embeddings = parameter((10, 8), .1)
        self.weights = nn.ParameterList([parameter((8, 8)) for _ in range(2)])
        with torch.no_grad():
            for weight in self.weights:
                weight.add_(torch.eye(8, dtype=torch.float64))
        self.attentions = nn.ParameterList([parameter((16,)) for _ in range(2)])
        self.head = parameter((104, 3))

    def import_reference(self, parameters):
        with torch.no_grad():
            self.input_projection.copy_(torch.as_tensor(parameters['input_projection']))
            self.node_embeddings.copy_(torch.as_tensor(parameters['node_embeddings']))
            self.head.copy_(torch.as_tensor(parameters['head']))
            for i, layer in enumerate(parameters['layers']):
                self.weights[i].copy_(torch.as_tensor(layer['weight']))
                self.attentions[i].copy_(torch.as_tensor(layer['attention']))
        if not all(torch.isfinite(p).all() for p in self.parameters()):
            raise ValueError('NONFINITE_PARAMETERS')

    def forward(self, values, observed):
        if values.ndim != 2 or values.shape[1] != 10 or values.shape != observed.shape or not len(values):
            raise ValueError('INVALID_GRAPH_INPUT')
        if observed.dtype != torch.bool or not torch.isfinite(values[observed]).all():
            raise ValueError('INVALID_OBSERVED_INPUT')
        channels = torch.stack((torch.where(observed, values, 0), observed.to(values.dtype)), dim=-1)
        encoded = F.relu(channels @ self.input_projection + self.node_embeddings)
        allowed = torch.as_tensor(allowed_routes(observed.detach().cpu().numpy(), self.edges))
        states = encoded
        attention, logits, messages = [], [], []
        for weight, a in zip(self.weights, self.attentions):
            q = states @ weight
            score = F.leaky_relu((q @ a[:8])[:, :, None] + (q @ a[8:])[:, None, :], .2)
            alpha = torch.softmax(score.masked_fill(~allowed, -torch.inf), dim=1)
            # Explicit per-edge message supports inspection of masked-route gradients.
            message = q[:, :, None, :].expand(-1, -1, 10, -1)
            states = F.relu((alpha[:, :, :, None] * message).sum(dim=1))
            attention.append(alpha); logits.append(score); messages.append(message)
        readout = (states.flatten(1) @ self.head[:80])[:, None, :] + self.head[80:][None, :, :]
        hazards = torch.softmax(readout, dim=2)
        survival = torch.cumprod(hazards[:, :, 0], dim=1)
        previous = torch.cat((torch.ones((len(values), 1), dtype=values.dtype), survival[:, :-1]), dim=1)
        cif = torch.stack(((previous * hazards[:, :, 1]).sum(1),
                           (previous * hazards[:, :, 2]).sum(1), survival[:, -1]), dim=1)
        return dict(encoded=encoded, states=states, allowed_routes=allowed, attention=attention,
                    logits=logits, messages=messages, readout=readout, hazards=hazards, cif=cif)


def state_digest(network):
    h = hashlib.sha256()
    for name, tensor in network.state_dict().items():
        h.update(name.encode()); h.update(tensor.detach().numpy().astype('<f8').tobytes())
    return h.hexdigest()


class GraphHazards(ClassifierMixin, BaseEstimator):
    """Adapter consumed by the existing person_period / predict_cif primitives."""
    def __init__(self, arm='prior', seed=20260926):
        self.arm = arm
        self.seed = seed

    @staticmethod
    def _input(frame):
        if list(frame.columns) != [*FEATURES, 'month'] or frame.empty:
            raise ValueError('EXACT_GRAPH_FEATURE_ORDER_REQUIRED')
        values = frame[list(FEATURES)].to_numpy(dtype=float)
        months = frame['month'].to_numpy(dtype=float)
        if (np.isinf(values).any() or not np.isfinite(months).all()
                or not np.isin(months, np.arange(1, 25)).all()):
            raise ValueError('INVALID_GRAPH_PERIODS')
        return values, months.astype(int) - 1

    def _transform(self, values):
        observed = ~np.isnan(values)
        imputed = np.where(observed, values, self.medians_)
        scaled = (imputed - self.mean_) / self.scale_
        return torch.as_tensor(np.where(observed, scaled, 0), dtype=torch.float64), torch.as_tensor(observed)

    def fit(self, X, y):
        values, months = self._input(X)
        y = np.asarray(y)
        if y.shape != (len(X),) or set(y.tolist()) != {0, 1, 2} or y.dtype.kind not in 'iu':
            raise ValueError('ALL_THREE_INTEGER_HAZARD_CLASSES_REQUIRED')
        started = time.perf_counter()
        spec, self.protocol_sha256_ = protocol()
        settings = spec['future_optimizer']
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        imputer = SimpleImputer(strategy='median', keep_empty_features=True)
        imputed = imputer.fit_transform(values)
        scale = StandardScaler().fit(imputed)
        self.medians_ = imputer.statistics_.copy()
        self.mean_ = scale.mean_.copy(); self.scale_ = scale.scale_.copy()
        self.network_ = GraphNetwork(self.arm, self.seed)
        self.initial_state_sha256_ = state_digest(self.network_)
        data, observed = self._transform(values)
        months = torch.as_tensor(months); labels = torch.as_tensor(y, dtype=torch.long)
        optimizer = torch.optim.Adam(self.network_.parameters(), lr=settings['learning_rate'],
                                     weight_decay=settings['weight_decay'])
        generator = torch.Generator().manual_seed(self.seed)
        batch_hash = hashlib.sha256(); self.loss_history_ = []
        for _ in range(settings['epochs']):
            order = torch.randperm(len(X), generator=generator)
            batch_hash.update(order.numpy().astype('<i8').tobytes())
            total = 0.
            for indices in order.split(settings['batch_person_months']):
                result = self.network_(data[indices], observed[indices])
                loss = F.cross_entropy(result['readout'][torch.arange(len(indices)), months[indices]], labels[indices])
                if not torch.isfinite(loss):
                    raise ValueError('NONFINITE_GRAPH_LOSS')
                optimizer.zero_grad(); loss.backward()
                nn.utils.clip_grad_norm_(self.network_.parameters(), settings['gradient_norm_clip'], error_if_nonfinite=True)
                optimizer.step(); total += float(loss.detach()) * len(indices)
            self.loss_history_.append(total / len(X))
        self.batch_schedule_sha256_ = batch_hash.hexdigest()
        self.classes_ = np.array([0, 1, 2]); self.n_features_in_ = 11
        self.fit_seconds_ = time.perf_counter() - started
        self.training_periods_ = len(X)
        self.training_input_sha256_ = hashlib.sha256(
            values.astype('<f8').tobytes() + months.numpy().astype('<i8').tobytes() + y.astype('<i8').tobytes()).hexdigest()
        if not all(torch.isfinite(p).all() for p in self.network_.parameters()):
            raise ValueError('NONFINITE_GRAPH_PARAMETERS')
        return self

    def predict_proba(self, X):
        values, months = self._input(X)
        if not hasattr(self, 'classes_') or self.protocol_sha256_ != protocol()[1]:
            raise ValueError('UNFITTED_OR_CHANGED_GRAPH_PROTOCOL')
        result = []
        with torch.no_grad():
            for start in range(0, len(X), 256):
                part = slice(start, start + 256)
                values_t, observed_t = self._transform(values[part])
                hazards = self.network_(values_t, observed_t)['hazards'].numpy()
                result.append(hazards[np.arange(len(hazards)), months[part]])
        probabilities = np.concatenate(result)
        if not np.isfinite(probabilities).all() or not np.allclose(probabilities.sum(1), 1, atol=1e-12, rtol=0):
            raise ValueError('INVALID_GRAPH_PROBABILITIES')
        return probabilities


def make_graph_estimator(arm, seed):
    return Pipeline([('hazards', GraphHazards(arm, seed))])


def save_graph(model, path, *, scope_identity):
    """New local artifacts only, NumPy tensor archive; no executable pickle."""
    estimator = model.named_steps['hazards']
    if not isinstance(scope_identity, str) or len(scope_identity) != 64:
        raise ValueError('GRAPH_COHORT_SPLIT_IDENTITY_REQUIRED')
    metadata = dict(schema='native-graph-tensors-v1', arm=estimator.arm, seed=estimator.seed,
                    protocol_sha256=estimator.protocol_sha256_, features=list(FEATURES),
                    scope_identity=scope_identity,
                    training_input_sha256=estimator.training_input_sha256_,
                    software={p: version(p) for p in PACKAGES}, source_sha256=digest(__file__),
                    clinical_use=False, individual_causal_effect_identified=False)
    arrays = {name: tensor.detach().numpy() for name, tensor in estimator.network_.state_dict().items()}
    arrays.update(medians=estimator.medians_, mean=estimator.mean_, scale=estimator.scale_,
                  metadata=np.frombuffer(json.dumps(metadata, sort_keys=True).encode(), dtype=np.uint8))
    with Path(path).open('xb') as stream:
        np.savez_compressed(stream, **arrays)
    return dict(path=Path(path).name, sha256=digest(path), **metadata)


def load_graph(path, expected_sha256, *, expected_arm, expected_training_input_sha256, expected_scope_identity):
    """Require caller-held artifact/input identities; archive loads with pickle disabled."""
    # Bind the bytes actually parsed, not a separate prior read of a replaceable file.
    from io import BytesIO
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('GRAPH_ARTIFACT_HASH_MISMATCH')
    with np.load(BytesIO(raw), allow_pickle=False) as arrays:
        metadata = json.loads(arrays['metadata'].tobytes())
        if (metadata['schema'] != 'native-graph-tensors-v1' or metadata['features'] != list(FEATURES)
                or metadata['protocol_sha256'] != protocol()[1] or metadata['arm'] != expected_arm
                or metadata['training_input_sha256'] != expected_training_input_sha256
                or metadata['scope_identity'] != expected_scope_identity
                or metadata['source_sha256'] != digest(__file__)
                or metadata['software'] != {p: version(p) for p in PACKAGES}
                or metadata['clinical_use'] or metadata['individual_causal_effect_identified']):
            raise ValueError('GRAPH_ARTIFACT_IDENTITY_MISMATCH')
        model = make_graph_estimator(metadata['arm'], metadata['seed'])
        estimator = model.named_steps['hazards']; estimator.network_ = GraphNetwork(estimator.arm, estimator.seed)
        state = estimator.network_.state_dict()
        if set(arrays.files) != set(state) | {'medians', 'mean', 'scale', 'metadata'}:
            raise ValueError('GRAPH_ARCHIVE_MEMBERS_MISMATCH')
        restored = {}
        for name, tensor in state.items():
            value = arrays[name]
            if value.shape != tuple(tensor.shape) or value.dtype != np.dtype('float64') or not np.isfinite(value).all():
                raise ValueError('INVALID_GRAPH_TENSOR')
            restored[name] = torch.as_tensor(value.copy())
        estimator.network_.load_state_dict(restored, strict=True)
        for name in ('medians', 'mean', 'scale'):
            value = arrays[name]
            if value.shape != (10,) or not np.isfinite(value).all() or (name == 'scale' and (value <= 0).any()):
                raise ValueError('INVALID_GRAPH_PREPROCESSING')
            setattr(estimator, name + '_', value.copy())
        estimator.protocol_sha256_ = metadata['protocol_sha256']
        estimator.training_input_sha256_ = metadata['training_input_sha256']
        estimator.classes_ = np.array([0, 1, 2]); estimator.n_features_in_ = 11
        return model
