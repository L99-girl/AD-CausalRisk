"""LIME-style weighted local surrogate on fixed-reference group coalitions.

The neighborhood is defined explicitly in binary group-presence space. It is
not a physiological distribution or a conditional resampling model. A local
surrogate fit never trains or recalibrates the underlying risk model.
"""
import hashlib

import numpy as np

from .group_shapley import _positive_int, _prepare_game, _predict_checked, graph_reference, _graph_float_frame


METHOD = 'binary-group-reference-local-surrogate-v1'


def local_surrogate(predict, values, reference, groups, *, samples=128,
                    seed=20261027, kernel_width=.75, ridge=1e-6,
                    max_evaluations=512, batch_predict=None, holdout_samples=0):
    """Fit one local two-output surrogate; preserve missingness and joint groups.

    Include reference and observed endpoints, sample other unique masks without
    replacement, then solve weighted least squares with ridge on slopes only.
    Report residual at the actual prediction; never enforce additive fidelity by
    distributing that residual across features. R2 describes the fitted sampled
    neighborhood, not held-out validation or clinical reliability.
    """
    _positive_int(samples, 'SAMPLE_BUDGET', 512)
    _positive_int(max_evaluations, 'COALITION_BUDGET', 512)
    if type(holdout_samples) is not int or not 0 <= holdout_samples <= 512:
        raise ValueError('INVALID_LOCAL_SURROGATE_HOLDOUT_BUDGET')
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError('INVALID_LOCAL_SURROGATE_SEED')
    if any(type(v) not in (int, float) or not np.isfinite(v) or v <= 0
           for v in (kernel_width, ridge)):
        raise ValueError('INVALID_LOCAL_SURROGATE_KERNEL_OR_RIDGE')
    x, ref, groups, names, _, active = _prepare_game(values, reference, groups)
    if len(x) != 1:
        raise ValueError('LOCAL_SURROGATE_REQUIRES_ONE_SUBJECT')
    players = len(active)
    count = min(samples, 2**players)
    if count > max_evaluations:
        raise ValueError('LOCAL_SURROGATE_EVALUATION_BUDGET_EXCEEDED')
    if players and count < players + 1:
        raise ValueError('INSUFFICIENT_LOCAL_SURROGATE_MASKS')
    if not players:
        output = _predict_checked(predict, ref.copy())
        return dict(method=METHOD, group_names=tuple(names), contributions=np.zeros((1, len(groups), 2)),
                    surrogate_intercept=output.copy(), reference_cif=output.copy(), prediction_cif=output.copy(),
                    surrogate_at_observed=output.copy(), observed_residual=np.zeros((1, 2)),
                    weighted_rmse=[0., 0.], weighted_r2=[None, None], design_rank=1,
                    neighborhood_evaluations=1, local_surrogate_fits=0, seed=seed,
                    kernel_width=kernel_width, ridge=ridge, is_causal_effect=False,
                    heldout_fidelity=dict(samples=0, status='NO_UNUSED_COALITIONS', weighted_rmse=None, weighted_r2=None))
    full = 2**players - 1
    if count == full + 1:
        codes = np.arange(full + 1, dtype=np.int64)
    else:
        middle = np.random.default_rng(seed).choice(np.arange(1, full), count-2, replace=False)
        codes = np.r_[0, np.sort(middle), full]
    unused = np.setdiff1d(np.arange(full+1), codes, assume_unique=True)
    holdout_count = min(holdout_samples, len(unused))
    if count + holdout_count > max_evaluations:
        raise ValueError('LOCAL_SURROGATE_EVALUATION_BUDGET_EXCEEDED')
    holdout_seed = (seed + 0x9e3779b9) % 2**32
    holdout_codes = np.sort(np.random.default_rng(holdout_seed).choice(unused, holdout_count, replace=False))
    masks = ((codes[:, None] >> np.arange(players)) & 1).astype(float)
    distance_squared = np.mean((1-masks)**2, axis=1)
    with np.errstate(over='ignore', divide='ignore', invalid='ignore'):
        weights = np.exp(-distance_squared/kernel_width**2)
    if not np.isfinite(weights).all() or (weights <= 0).any():
        raise ValueError('LOCAL_SURROGATE_KERNEL_UNDERFLOW')
    def evaluate_masks(binary_masks):
        states = np.repeat(ref, len(binary_masks), axis=0)
        for row, mask in enumerate(binary_masks):
            for bit, group in enumerate(active):
                if mask[bit]:
                    cols = list(groups[group][1])
                    states[row, cols] = x[0, cols]
        if batch_predict is None:
            return np.vstack([_predict_checked(predict, state[None, :].copy()) for state in states])
        return _predict_checked(batch_predict, states)
    outcomes = evaluate_masks(masks)
    design = np.c_[np.ones(count), masks]
    root_weight = np.sqrt(weights[:, None])
    penalty = np.c_[np.zeros(players), np.eye(players)] * np.sqrt(ridge)
    augmented = np.vstack([design*root_weight, penalty])
    targets = np.vstack([outcomes*root_weight, np.zeros((players, 2))])
    coefficients, _, _, _ = np.linalg.lstsq(augmented, targets, rcond=None)
    if not np.isfinite(coefficients).all():
        raise ValueError('NONFINITE_LOCAL_SURROGATE_COEFFICIENTS')
    fitted = design @ coefficients
    mean = np.average(outcomes, axis=0, weights=weights)
    error = np.sum(weights[:, None]*(outcomes-fitted)**2, axis=0)
    variation = np.sum(weights[:, None]*(outcomes-mean)**2, axis=0)
    r2 = [float(1-error[i]/variation[i]) if variation[i] > 1e-15 else None for i in range(2)]
    contributions = np.zeros((1, len(groups), 2))
    contributions[0, active] = coefficients[1:]
    surrogate_at_observed = coefficients.sum(axis=0)[None, :]
    heldout = dict(samples=0, status='NOT_REQUESTED' if not holdout_samples else 'NO_UNUSED_COALITIONS',
                   weighted_rmse=None, weighted_r2=None)
    if holdout_count:
        test_masks = ((holdout_codes[:, None] >> np.arange(players)) & 1).astype(float)
        test_outcomes = evaluate_masks(test_masks)
        test_weights = np.exp(-np.mean((1-test_masks)**2, axis=1)/kernel_width**2)
        test_fitted = np.c_[np.ones(holdout_count), test_masks] @ coefficients
        test_mean = np.average(test_outcomes, axis=0, weights=test_weights)
        test_error = np.sum(test_weights[:, None]*(test_outcomes-test_fitted)**2, axis=0)
        test_variation = np.sum(test_weights[:, None]*(test_outcomes-test_mean)**2, axis=0)
        heldout = dict(samples=holdout_count, status='DISJOINT_UNUSED_COALITIONS',
                       weighted_rmse=np.sqrt(test_error/test_weights.sum()).tolist(),
                       weighted_r2=[float(1-test_error[i]/test_variation[i]) if test_variation[i] > 1e-15 else None for i in range(2)],
                       mask_sha256=hashlib.sha256(holdout_codes.astype('<i8').tobytes()).hexdigest(),
                       seed=holdout_seed)
    return dict(
        method=METHOD, group_names=tuple(names), contributions=contributions,
        surrogate_intercept=coefficients[0][None, :], reference_cif=outcomes[0][None, :],
        prediction_cif=outcomes[-1][None, :], surrogate_at_observed=surrogate_at_observed,
        observed_residual=outcomes[-1][None, :]-surrogate_at_observed,
        weighted_rmse=np.sqrt(error/weights.sum()).tolist(), weighted_r2=r2,
        design_rank=int(np.linalg.matrix_rank(design)),
        neighborhood_evaluations=count, local_surrogate_fits=1, seed=seed,
        kernel_width=kernel_width, ridge=ridge, is_causal_effect=False,
        mask_sha256=hashlib.sha256(codes.astype('<i8').tobytes()).hexdigest(),
        heldout_fidelity=heldout,
    )


def explain_graph(model, frame, *, samples=128, seed=20261027,
                  kernel_width=.75, ridge=1e-6, max_evaluations=512,
                  reference_kind='median', batch_predictions=False, holdout_samples=0):
    """Explain one verified in-memory case/model; never load files or save a case."""
    from .graph_explanation import GROUPS, Calls, model_identity, observation_groups
    from .graph_native import FEATURES
    if len(frame) != 1:
        raise ValueError('LOCAL_SURROGATE_REQUIRES_ONE_SUBJECT')
    if type(batch_predictions) is not bool:
        raise ValueError('INVALID_LOCAL_SURROGATE_BATCH_OPTION')
    snapshot = frame.copy(deep=True)
    observation_groups(snapshot)
    identity = model_identity(model)
    reference = graph_reference(model, snapshot, reference_kind)
    groups = tuple((name, tuple(FEATURES.index(c) for c in cols)) for name, cols in GROUPS)
    calls = Calls(max_evaluations)

    def predict(state):
        current = _graph_float_frame(snapshot)
        current.loc[:, list(FEATURES)] = state
        return calls(model, current)

    def predict_batch(states):
        # Unique ephemeral state IDs satisfy the existing CIF row contract.
        # A state is not another participant or a newly observed clinical row.
        current = _graph_float_frame(snapshot).iloc[np.zeros(len(states), dtype=int)].reset_index(drop=True).copy()
        current.loc[:, 'subject_id'] = [f'XAI-STATE-{i}' for i in range(len(states))]
        current.loc[:, list(FEATURES)] = states
        return calls(model, current)

    result = local_surrogate(predict, _graph_float_frame(snapshot)[list(FEATURES)].to_numpy(),
                             reference[list(FEATURES)].to_numpy(), groups, samples=samples,
                             seed=seed, kernel_width=kernel_width, ridge=ridge,
                             max_evaluations=max_evaluations,
                             batch_predict=predict_batch if batch_predictions else None,
                             holdout_samples=holdout_samples)
    if model_identity(model) != identity or not frame.equals(snapshot):
        raise ValueError('LOCAL_SURROGATE_MODEL_OR_INPUT_CHANGED')
    result.update(model_identity=identity, reference_policy='outer_training_person_month_'+('medians' if reference_kind == 'median' else 'means'),
                  cif_calls=calls.count, predictive_fits=0, calibration_fits=0)
    return result
