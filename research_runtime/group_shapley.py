"""Exact single-reference, grouped Shapley values for two-cause CIF predictions.

No fitting, file readers or persistence. These are prediction attributions for a
specified replacement game, not conditional expectations or causal effects.
"""
from math import comb

import numpy as np


METHOD = 'exact-single-reference-group-shapley-v1'
MAX_GROUPS = 9
MAX_ROWS = 256
TOLERANCE = 1e-12


def _positive_int(value, name, upper):
    if type(value) is not int or not 1 <= value <= upper:
        raise ValueError('INVALID_SHAPLEY_' + name)


def _prepare_game(values, reference, groups):
    x = np.asarray(values)
    ref = np.asarray(reference)
    if (x.dtype.kind not in 'fi' or ref.dtype.kind not in 'fi'
            or x.ndim != 2 or x.shape != ref.shape
            or not 1 <= x.shape[0] <= MAX_ROWS or x.shape[1] == 0):
        raise ValueError('INVALID_SHAPLEY_INPUT')
    x = x.astype(float, copy=True)
    ref = ref.astype(float, copy=True)
    if (np.isinf(x).any() or np.isinf(ref).any()
            or not np.array_equal(np.isnan(x), np.isnan(ref))):
        raise ValueError('SHAPLEY_REFERENCE_CHANGED_MISSINGNESS')
    groups = tuple(groups)
    if not 1 <= len(groups) <= MAX_GROUPS:
        raise ValueError('INVALID_SHAPLEY_GROUPS')
    names, columns = [], []
    for item in groups:
        if (not isinstance(item, (tuple, list)) or len(item) != 2
                or not isinstance(item[0], str) or not item[0]
                or not isinstance(item[1], (tuple, list)) or not item[1]
                or any(type(i) is not int for i in item[1])):
            raise ValueError('INVALID_SHAPLEY_GROUPS')
        names.append(item[0])
        columns.extend(item[1])
    if (len(set(names)) != len(names) or len(set(columns)) != len(columns)
            or sorted(columns) != list(range(x.shape[1]))):
        raise ValueError('SHAPLEY_GROUPS_MUST_PARTITION_FEATURES')
    equal = (x == ref) | (np.isnan(x) & np.isnan(ref))
    row_changed = np.column_stack([
        ~equal[:, list(indices)].all(axis=1) for _, indices in groups
    ])
    active = np.flatnonzero(row_changed.any(axis=0)).tolist()
    return x, ref, groups, names, row_changed, active


def _predict_checked(predict, state):
    before = state.copy()
    state.flags.writeable = False
    raw = np.asarray(predict(state))
    if not np.array_equal(state, before, equal_nan=True):
        raise ValueError('SHAPLEY_PREDICT_MUTATED_INPUT')
    if (raw.dtype.kind not in 'fi' or raw.shape != (len(state), 2)
            or not np.isfinite(raw).all() or (raw < 0).any()
            or (raw > 1).any() or (raw.sum(axis=1) > 1 + TOLERANCE).any()):
        raise ValueError('INVALID_SHAPLEY_TWO_CAUSE_CIF')
    return raw.astype(float, copy=True)


def exact_values(predict, values, reference, groups, *, max_coalitions=512):
    """Explain row-independent, deterministic two-cause probability predictions.

    ``groups`` partitions all feature columns as (name, tuple(column_indices)).
    Reference and observed arrays have the same NaN pattern. A group's columns
    are replaced together; omitted groups retain the caller-supplied reference.
    All subsets of the groups that differ from reference are evaluated once.
    Globally unchanged groups are dummy players and receive exactly zero.

    Arrays returned in memory are individual outputs: the caller is responsible
    for authorized use. This function never saves or logs their contents.
    """
    _positive_int(max_coalitions, 'COALITION_BUDGET', 2 ** MAX_GROUPS)
    x, ref, groups, names, row_changed, active = _prepare_game(values, reference, groups)
    count = 2 ** len(active)
    if count > max_coalitions:
        raise ValueError('SHAPLEY_COALITION_BUDGET_EXCEEDED')

    outputs = np.empty((count, len(x), 2), dtype=float)
    for mask in range(count):
        state = ref.copy()
        for bit, group in enumerate(active):
            if mask & (1 << bit):
                cols = list(groups[group][1])
                state[:, cols] = x[:, cols]
        outputs[mask] = _predict_checked(predict, state)

    contributions = np.zeros((len(x), len(groups), 2), dtype=float)
    players = len(active)
    for bit, group in enumerate(active):
        for mask in range(count):
            if mask & (1 << bit):
                continue
            size = mask.bit_count()
            weight = 1 / (players * comb(players - 1, size))
            contributions[:, group] += weight * (
                outputs[mask | (1 << bit)] - outputs[mask]
            )
    if np.any(np.abs(contributions[~row_changed]) > TOLERANCE):
        raise ValueError('SHAPLEY_DUMMY_GROUP_INCONSISTENT')
    contributions[~row_changed] = 0.
    error = float(np.max(np.abs(outputs[0] + contributions.sum(axis=1) - outputs[-1])))
    if error > TOLERANCE:
        raise ValueError('SHAPLEY_LOCAL_ACCURACY_FAILED')
    return {
        'method': METHOD, 'group_names': tuple(names),
        'reference_cif': outputs[0].copy(), 'prediction_cif': outputs[-1].copy(),
        'contributions': contributions, 'coalition_evaluations': count,
        'active_groups': tuple(names[i] for i in active),
        'reconstruction_max_error': error,
        'reference_policy': 'caller_supplied_same_missingness',
        'is_causal_effect': False,
    }


def _graph_float_frame(frame):
    """Use floating replacement columns in a copy, including nullable integers."""
    from .graph_native import FEATURES
    return frame.astype({name: 'float64' for name in FEATURES}, copy=True)


def graph_reference(model, frame, reference_kind='median'):
    """Preserve masks using saved training-person-month statistics only."""
    from .graph_explanation import median_reference
    if reference_kind not in ('median', 'mean'):
        raise ValueError('INVALID_GRAPH_EXPLANATION_REFERENCE_KIND')
    stats = getattr(model.named_steps['hazards'], 'medians_' if reference_kind == 'median' else 'mean_')
    return median_reference(_graph_float_frame(frame), stats)


def explain_graph(model, frame, *, max_coalitions=512, reference_kind='median'):
    """Use the existing graph model's training medians and unchanged CIF path.

    No model or clinical files are loaded. Caller supplies a verified in-memory
    model and qualified frame; this adapter does not certify their provenance,
    fold membership, date/QC eligibility or permission for individual outputs.
    """
    from .graph_explanation import (
        GROUPS, Calls, model_identity, observation_groups,
    )
    from .graph_native import FEATURES

    _positive_int(max_coalitions, 'COALITION_BUDGET', 512)
    if not 1 <= len(frame) <= MAX_ROWS:
        raise ValueError('INVALID_SHAPLEY_INPUT')
    snapshot = frame.copy(deep=True)
    observation_groups(snapshot)  # Reject partial bilateral observations.
    identity = model_identity(model)
    reference = graph_reference(model, snapshot, reference_kind)
    groups = tuple((name, tuple(FEATURES.index(c) for c in columns)) for name, columns in GROUPS)
    calls = Calls(max_coalitions)

    def predict(state):
        current = _graph_float_frame(snapshot)
        current.loc[:, list(FEATURES)] = state
        return calls(model, current)

    result = exact_values(
        predict, _graph_float_frame(snapshot)[list(FEATURES)].to_numpy(),
        reference[list(FEATURES)].to_numpy(), groups,
        max_coalitions=max_coalitions,
    )
    if model_identity(model) != identity or not frame.equals(snapshot):
        raise ValueError('SHAPLEY_MODEL_OR_INPUT_CHANGED')
    result.update(model_identity=identity, reference_policy='outer_training_person_month_'+('medians' if reference_kind == 'median' else 'means'),
                  cif_calls=calls.count, fits=0)
    return result
