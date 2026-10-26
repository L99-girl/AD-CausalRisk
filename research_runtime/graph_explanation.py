"""Fixed-weight OOF explanation diagnostics; no readers, fitting or case outputs."""
from copy import deepcopy
from itertools import combinations
import hashlib
import json
import time
import warnings

import numpy as np
from scipy.stats import spearmanr
import torch

from . import graph
from .graph_native import FEATURES, state_digest
from .graph_training import checked_cif
from .training import checked_design, input_fingerprint, prediction_hash
from .evaluation import censor_survival, horizon_ipcw_weights
from .graph_acceptance import peak_memory_bytes

GROUPS = tuple((name, (name,)) for name in FEATURES[:8]) + (('bilateral_hippocampus', FEATURES[8:]),)
ORDERS = ('forward', 'reverse')
TOLERANCE = 1e-12
MATERIAL = 1e-6


def model_identity(model):
    e = model.named_steps['hazards']; h = hashlib.sha256(state_digest(e.network_).encode())
    h.update(repr((e.arm, e.seed, e.network_.arm, e.network_.edges, e.protocol_sha256_, e.network_.training)).encode())
    for values in (e.medians_, e.mean_, e.scale_, e.classes_):h.update(np.asarray(values).tobytes())
    return h.hexdigest()


class Calls:
    def __init__(self, limit=1230):self.count = 0; self.limit = limit
    def __call__(self, model, frame):
        if self.count >= self.limit:raise ValueError('EXPLANATION_CIF_BUDGET_EXCEEDED')
        self.count += 1
        before = model_identity(model); fingerprint = input_fingerprint(frame, 'multimodal_values')
        result = checked_cif(model, frame)
        if model_identity(model) != before or input_fingerprint(frame, 'multimodal_values') != fingerprint:
            raise ValueError('EXPLANATION_MODEL_OR_INPUT_MUTATED')
        return result


def observation_groups(frame):
    masks = []
    for _, columns in GROUPS:
        observed = frame[list(columns)].notna().to_numpy()
        if not (observed == observed[:, :1]).all():raise ValueError('PARTIAL_EXPLANATION_GROUP')
        masks.append(observed.all(1))
    return np.column_stack(masks)


def median_reference(frame, medians):
    medians = np.asarray(medians)
    if medians.shape != (10,) or not np.isfinite(medians).all():raise ValueError('INVALID_GRAPH_REFERENCE')
    result = frame.copy(deep=True)
    for index, name in enumerate(FEATURES):result.loc[result[name].notna(), name] = medians[index]
    if not np.array_equal(result[list(FEATURES)].isna(), frame[list(FEATURES)].isna()):
        raise ValueError('REFERENCE_CHANGED_OBSERVATION_MASK')
    return result


def telescoping(model, frame, baseline, calls):
    reference = median_reference(frame, model.named_steps['hazards'].medians_)
    start = calls(model, reference); observed = observation_groups(frame); result = {}
    maximum = 0.
    for order in ORDERS:
        indices = list(range(9)) if order == 'forward' else list(reversed(range(9)))
        state = reference.copy(deep=True); previous = start
        contributions = np.zeros((len(frame), 9, 2))
        for step, group in enumerate(indices):
            columns = list(GROUPS[group][1]); state.loc[:, columns] = frame[columns].to_numpy()
            current = baseline if step == 8 else calls(model, state)
            contributions[:, group] = current-previous; previous = current
        residual = float(np.max(np.abs(start+contributions.sum(1)-baseline)))
        if residual > TOLERANCE or np.any(contributions[~observed] != 0):
            raise ValueError('CIF_EXPLANATION_RECONSTRUCTION_OR_MISSINGNESS_FAILURE')
        maximum = max(maximum, residual); result[order] = contributions
    return start, result, maximum


def without_routes(model, removed):
    original = tuple(model.named_steps['hazards'].network_.edges)
    removed = tuple(removed)
    if len(set(removed)) != len(removed) or not set(removed).issubset(original):
        raise ValueError('UNUSED_OR_DUPLICATE_ROUTE_REMOVAL')
    result = deepcopy(model)
    result.named_steps['hazards'].network_.edges = tuple(edge for edge in original if edge not in removed)
    if state_digest(result.named_steps['hazards'].network_) != state_digest(model.named_steps['hazards'].network_):
        raise ValueError('ROUTE_DIAGNOSTIC_CHANGED_PARAMETERS')
    return result


def trace(model, frame, baseline):
    e = model.named_steps['hazards']; before = model_identity(model)
    if tuple(e.network_.edges) != graph.arm_edges(e.arm):raise ValueError('DISPLAY_GRAPH_DIFFERS_FROM_PREDICTOR')
    values, observed = e._transform(frame[list(FEATURES)].to_numpy(float))
    with torch.no_grad():result = e.network_(values, observed)
    parameters = {'input_projection':e.network_.input_projection.detach().numpy(),
                  'node_embeddings':e.network_.node_embeddings.detach().numpy(),
                  'head':e.network_.head.detach().numpy(),
                  'layers':[{'weight':w.detach().numpy(), 'attention':a.detach().numpy()}
                            for w, a in zip(e.network_.weights, e.network_.attentions)]}
    reference = graph.reference_forward(values.numpy(), observed.numpy(), e.arm, parameters)
    allowed = result['allowed_routes'].numpy(); errors = []
    if not np.array_equal(allowed, reference['allowed_routes']):raise ValueError('ACTUAL_GATE_MISMATCH')
    for i, alpha in enumerate(result['attention']):
        alpha = alpha.numpy()
        if np.any(alpha[~allowed] != 0) or not np.allclose(alpha.sum(1), 1, rtol=0, atol=TOLERANCE):
            raise ValueError('ACTUAL_ATTENTION_GATE_OR_NORMALIZATION_FAILURE')
        errors.append(float(np.max(np.abs(alpha-reference['attention'][i]))))
    for name in ('encoded', 'states', 'hazards', 'cif'):
        errors.append(float(np.max(np.abs(result[name].numpy()-reference[name]))))
    # Additive contributions apply to logits, not directly to nonlinear CIFs.
    node_logits = np.einsum('njd,jdc->njc', result['states'].numpy(), parameters['head'][:80].reshape(10, 8, 3))
    readout = node_logits.sum(1)[:, None, :]+parameters['head'][80:][None]
    errors.append(float(np.max(np.abs(readout-result['readout'].numpy()))))
    errors.append(float(np.max(np.abs(result['cif'].numpy()[:, :2]-baseline))))
    if not np.isfinite(errors).all() or max(errors) > TOLERANCE or model_identity(model) != before:
        raise ValueError('ACTUAL_TRACE_RECONSTRUCTION_FAILURE')
    edges = graph.arm_edges(e.arm)
    attention = np.column_stack([np.mean([a.numpy()[:, s, t] for a in result['attention']], axis=0)
                                 for s, t in edges]) if edges else np.zeros((len(frame), 0))
    active = np.column_stack([allowed[:, s, t] for s, t in edges]) if edges else np.zeros((len(frame), 0), bool)
    return attention, active, max(errors)


def descriptive(values):
    values = np.asarray(values, dtype=float)
    if not np.isfinite(values).all():raise ValueError('NONFINITE_EXPLANATION_SUMMARY')
    return dict(n=len(values), mean=float(values.mean()) if len(values) else None,
                median=float(np.median(values)) if len(values) else None,
                p95=float(np.quantile(values, .95)) if len(values) else None)


def rank(left, right):
    left, right = np.asarray(left), np.asarray(right)
    if len(left) < 2 or np.ptp(left) <= TOLERANCE or np.ptp(right) <= TOLERANCE:return None
    return float(spearmanr(left, right).statistic)


def local_rank_summary(left, right, observed):
    values = []; insufficient = constant = 0
    for a, b, mask in zip(left, right, observed):
        if mask.sum() < 3:insufficient += 1; continue
        value = rank(np.abs(a[mask]), np.abs(b[mask]))
        if value is None:constant += 1
        else:values.append(value)
    return dict(spearman=descriptive(values), insufficient_observed_groups=insufficient, constant_ranks=constant)


def aggregate(work, splits, raw, references, contributions, edge_deltas, all_route_deltas, attentions, active):
    spec, _ = graph.protocol(); seeds = spec['future_initialization_seeds']; n = len(work)
    observed = observation_groups(work); rows = []; sensitivity = []; seed_rows = []; fold_rows = []
    means = {}
    for arm in spec['arms']:
        means[arm] = {}
        for order in ORDERS:
            values = np.stack([contributions[s, arm, order] for s in seeds]); mean = values.mean(0)
            means[arm][order] = mean[:, :, 0]
            rows.append(dict(arm=arm, order=order, method='fixed-reference ordered telescoping CIF',
                groups=[dict(group=name, observed_subjects=int(observed[:, j].sum()),
                     mean_signed_ad=float(mean[:, j, 0].mean()), mean_abs_ad=float(np.abs(mean[:, j, 0]).mean()),
                     mean_signed_other=float(mean[:, j, 1].mean()), mean_abs_other=float(np.abs(mean[:, j, 1]).mean()),
                     observed_mean_abs_ad=float(np.abs(mean[observed[:, j], j, 0]).mean()) if observed[:, j].any() else None)
                     for j, (name, _) in enumerate(GROUPS)]))
            for a, b in combinations(seeds, 2):
                seed_rows.append(dict(arm=arm, order=order, seeds=[a, b],
                    global_magnitude_spearman=rank(np.abs(contributions[a, arm, order][:, :, 0]).mean(0),
                                                   np.abs(contributions[b, arm, order][:, :, 0]).mean(0)),
                    local=local_rank_summary(contributions[a, arm, order][:, :, 0], contributions[b, arm, order][:, :, 0], observed)))
            vectors = [np.abs(mean[b, :, 0]).mean(0) for _, b in splits]
            for a, b in combinations(range(5), 2):
                fold_rows.append(dict(arm=arm, order=order, folds=[a+1, b+1], magnitude_spearman=rank(vectors[a], vectors[b])))
        forward, reverse = means[arm]['forward'], means[arm]['reverse']
        difference = np.abs(forward-reverse).sum(1)
        material = (np.abs(forward) > MATERIAL) & (np.abs(reverse) > MATERIAL) & observed
        flips = (forward*reverse < 0) & material
        sensitivity.append(dict(arm=arm, local_order_l1=descriptive(difference),
            subjects_above_1e_6=int((difference > MATERIAL).sum()),
            material_group_contributions=int(material.sum()), sign_flips=int(flips.sum()),
            local_order_ranks=local_rank_summary(forward, reverse, observed)))
    routes = []; attention_checks = []
    for arm in spec['arms']:
        edges = graph.arm_edges(arm)
        total = np.stack([all_route_deltas[s, arm] for s in seeds]).mean(0)
        delta = np.stack([edge_deltas[s, arm] for s in seeds]).mean(0)
        attention = np.stack([attentions[s, arm] for s in seeds]).mean(0)
        mask = active[arm]
        routes.append(dict(arm=arm, all_cross_routes_removed_mean_abs_ad=float(np.abs(total[:, 0]).mean()),
            all_cross_routes_removed_mean_signed_ad=float(total[:, 0].mean()),
            effective_cross_routes=descriptive(mask.sum(1)),
            edges=[dict(source=FEATURES[s], target=FEATURES[t], active_subjects=int(mask[:, j].sum()),
                        mean_attention=float(attention[:, j].mean()),
                        mean_abs_ad_change=float(np.abs(delta[:, j, 0]).mean()),
                        mean_signed_ad_change=float(delta[:, j, 0].mean())) for j, (s, t) in enumerate(edges)]))
        corrs = []; eligible = matches = insufficient = constant = 0
        for person in range(n):
            supported = mask[person]
            if supported.sum() < 2:insufficient += 1; continue
            magnitude = np.abs(delta[person, supported, 0]); weights = attention[person, supported]
            value = rank(weights, magnitude)
            if value is None or magnitude.max() <= TOLERANCE:constant += 1; continue
            eligible += 1; corrs.append(value)
            chosen = int(np.argmax(weights))
            matches += int(magnitude[chosen] >= magnitude.max()-TOLERANCE)
        attention_checks.append(dict(arm=arm, eligible_subjects=eligible, top_attention_matches_top_deletion=matches,
            top_agreement_fraction=matches/eligible if eligible else None, magnitude_spearman=descriptive(corrs),
            insufficient_active_edges=insufficient, constant_attention_or_effect=constant))
    cross = [dict(order=order, arms=[a, b],
                  global_magnitude_spearman=rank(np.abs(means[a][order]).mean(0), np.abs(means[b][order]).mean(0)),
                  local=local_rank_summary(means[a][order], means[b][order], observed))
             for order in ORDERS for a, b in combinations(spec['arms'], 2)]
    return dict(importance=rows, order_sensitivity=sensitivity, seed_sensitivity=seed_rows,
                fold_sensitivity=fold_rows, cross_arm_sensitivity=cross,
                route_sensitivity=routes, attention_vs_deletion=attention_checks)


def evaluate(frame, splits, loader, expected, progress=lambda value:None):
    work, splits, _ = checked_design(frame, 'multimodal_values', splits)
    spec, protocol_hash = graph.protocol(); seeds = spec['future_initialization_seeds']; arms = spec['arms']
    torch.set_num_threads(1); started = time.perf_counter(); calls = Calls()
    n = len(work); weights = np.full(n, np.nan); target = work.event_type.eq(1).to_numpy(float)
    raw = {(s, a):np.full((n, 2), np.nan) for s in seeds for a in arms}
    references = {key:np.full((n, 2), np.nan) for key in raw}
    contributions = {(s, a, o):np.full((n, 9, 2), np.nan) for s, a in raw for o in ORDERS}
    edge_deltas = {(s, a):np.full((n, len(graph.arm_edges(a)), 2), np.nan) for s, a in raw}
    all_deltas = {key:np.full((n, 2), np.nan) for key in raw}
    attentions = {(s, a):np.full((n, len(graph.arm_edges(a))), np.nan) for s, a in raw}
    active = {a:np.zeros((n, len(graph.arm_edges(a))), bool) for a in arms}
    models = {}; identities = {}; baseline_rows = []; loads = traces = 0
    reconstruction_max = trace_max = 0.
    for fold, (a, b) in enumerate(splits, 1):
        weights[b] = horizon_ipcw_weights(work.iloc[b], censor_survival(work.iloc[a]))
        for seed in seeds:
            for arm in arms:
                model = loader(arm, seed, fold); loads += 1
                if (model.named_steps['hazards'].arm != arm or model.named_steps['hazards'].seed != seed):
                    raise ValueError('EXPLANATION_MODEL_ROLE_MISMATCH')
                models[fold, seed, arm] = model; identities[fold, seed, arm] = model_identity(model)
                raw[seed, arm][b] = calls(model, work.iloc[b])
    for arm in arms:
        row = next(row for row in expected['models'] if row['arm'] == arm)
        for seed in seeds:
            old = next(value for value in row['per_seed'] if value['seed'] == seed)
            if prediction_hash(raw[seed, arm][:, 0]) != old['ad_oof_sha256'] or prediction_hash(raw[seed, arm][:, 1]) != old['other_oof_sha256']:
                raise ValueError('ORIGINAL_TWO_CAUSE_SEED_OOF_CHANGED')
        mean = np.stack([raw[s, arm] for s in seeds]).mean(0)
        if (prediction_hash(mean[:, 0]) != row['ad_oof_sha256'] or prediction_hash(mean[:, 1]) != row['other_oof_sha256']
                or abs(float(np.mean(weights*(target-mean[:, 0])**2))-row['pooled_oof_brier']) > TOLERANCE):
            raise ValueError('ORIGINAL_ENSEMBLE_OOF_OR_BRIER_CHANGED')
        baseline_rows.append(dict(arm=arm, ad_oof_sha256=prediction_hash(mean[:, 0]),
                                 other_oof_sha256=prediction_hash(mean[:, 1]), brier=row['pooled_oof_brier']))
    progress(dict(all_two_cause_baselines_verified=True, model_loads=loads, cif_calls=calls.count))
    for fold, (_, b) in enumerate(splits, 1):
        test = work.iloc[b]
        for seed in seeds:
            for arm in arms:
                model = models[fold, seed, arm]; baseline = raw[seed, arm][b]; edges = graph.arm_edges(arm)
                attention, allowed, error = trace(model, test, baseline); traces += 1
                trace_max = max(trace_max, error); attentions[seed, arm][b] = attention
                active[arm][b] = allowed
                reference, values, error = telescoping(model, test, baseline, calls)
                references[seed, arm][b] = reference; reconstruction_max = max(reconstruction_max, error)
                for order in ORDERS:contributions[seed, arm, order][b] = values[order]
                all_delta = baseline-calls(without_routes(model, edges), test)
                all_deltas[seed, arm][b] = all_delta
                if not edges and np.any(all_delta != 0):raise ValueError('SELF_ONLY_ROUTE_ABLATION_NOT_ZERO')
                for j, edge in enumerate(edges):
                    delta = baseline-calls(without_routes(model, (edge,)), test)
                    if np.any(delta[~allowed[:, j]] != 0):raise ValueError('INACTIVE_ROUTE_HAS_PREDICTIVE_EFFECT')
                    edge_deltas[seed, arm][b, j] = delta
                if not np.array_equal(calls(model, test), baseline) or model_identity(model) != identities[fold, seed, arm]:
                    raise ValueError('EXPLANATION_CHANGED_ORIGINAL_MODEL_OR_CIF')
                if time.perf_counter()-started > 1800 or peak_memory_bytes() > 2147483648:
                    raise ValueError('EXPLANATION_RESOURCE_LIMIT_EXCEEDED')
        progress(dict(completed_explanation_fold=fold, cif_calls=calls.count, trace_pairs=traces, model_loads=loads))
    if calls.count != 1230 or loads != 45 or traces != 45:raise ValueError('INCOMPLETE_EXPLANATION_BUDGET')
    summary = aggregate(work, splits, raw, references, contributions, edge_deltas, all_deltas, attentions, active)
    return dict(status='FIXED_GRAPH_EXPLANATION_AND_FAITHFULNESS_COMPLETE', subjects=n, outer_folds=5,
        protocol_sha256=protocol_hash, baseline=baseline_rows, **summary,
        existing_model_loads=loads, cif_calls=calls.count, native_numpy_trace_pairs=traces,
        cif_reconstruction_max_error=reconstruction_max, trace_reconstruction_max_error=trace_max,
        tolerance=TOLERANCE, fits=0, calibration_fits=0,
        elapsed_seconds=time.perf_counter()-started, peak_process_memory_bytes=peak_memory_bytes(),
        clinical_use=False, individual_causal_effect_identified=False, external_validation=False,
        default_model_changed=False, participant_predictions_saved=False, participant_explanations_saved=False,
        explanation_type='fixed-reference, order-dependent predictive decomposition; fixed-weight route deletion',
        limitations=['Exact additivity does not establish uniqueness, biological reference validity or causality.',
            'Canonical/reverse orders are two fixed diagnostics, not Shapley averaging or SHAP/LIME.',
            'Route deletion includes renormalization and downstream messages; it is not an additive edge attribution.',
            'Attention is a computational weight; agreement with deletion is descriptive and not causal fidelity.',
            'Fixed stored models and cohort; no new bootstrap, significance, independent or refit uncertainty.',
            'Retrospective MRI/as-of/QC/ICV limits, six cross-connected nodes and five competing events remain.'])
