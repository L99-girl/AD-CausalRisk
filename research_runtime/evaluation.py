"""Original fold-contained IPCW, calibration and descriptive metrics.

Selected functions retain the original AST; no host imports or data readers.
"""
from __future__ import annotations
import warnings
import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold
SEED = 20260926
EPS = 1e-6
BIN_EDGES = (0., .2, .4, .6, .8, 1.)
MIN_KNOWN_PER_BIN = 5
ExecutionError = ValueError


def censor_survival(train: pd.DataFrame) -> np.ndarray:
    """Marginal Kaplan-Meier G(t) for censoring, fitted within a training fold."""
    time = train.observed_month.to_numpy(dtype=int)
    censored = (train.event_type.to_numpy(dtype=int) == 0) & (time < 24)
    g = np.ones(25, dtype=float)
    for month in range(1, 25):
        risk = int((time >= month).sum())
        count = int((censored & (time == month)).sum())
        g[month] = g[month - 1] * (1 - count / risk) if risk else g[month - 1]
    return g


def horizon_ipcw_weights(test: pd.DataFrame, g: np.ndarray, cap: float = 0.05) -> np.ndarray:
    """Weights for known 24-month outcomes; early censoring receives zero."""
    if len(g) != 25 or not np.isfinite(g).all() or not 0 < cap <= 1:
        raise ValueError("Invalid censor survival curve or IPCW cap")
    event = test.event_type.to_numpy(dtype=int)
    time = test.observed_month.to_numpy(dtype=int)
    weights = np.zeros(len(test), dtype=float)
    event_rows = event != 0
    weights[event_rows] = 1 / np.maximum(g[np.maximum(time[event_rows] - 1, 0)], cap)
    complete = (event == 0) & (time == 24)
    weights[complete] = 1 / max(g[24], cap)
    return weights


def horizon_metrics(test: pd.DataFrame, scores: np.ndarray, g: np.ndarray) -> dict[str, float]:
    event = test.event_type.to_numpy(dtype=int)
    time = test.observed_month.to_numpy(dtype=int)
    known = (event != 0) | (time == 24)
    weights = horizon_ipcw_weights(test, g)
    y = (event == 1).astype(int)
    if not known.any() or np.unique(y[known]).size < 2:
        raise ValueError("Holdout fold lacks known AD event and non-event outcomes")
    return {
        "ipcw_roc_auc": float(roc_auc_score(y[known], scores[known], sample_weight=weights[known])),
        "ipcw_pr_auc": float(average_precision_score(y[known], scores[known], sample_weight=weights[known])),
        "ipcw_brier_24m": float(np.sum(weights * (y - scores) ** 2) / len(test)),
        "known_horizon_fraction": float(known.mean()),
        "mean_predicted_ad_cif": float(scores.mean()),
    }


def paired_interval(subject_differences: np.ndarray, *, seed: int = 20260929,
                    n_resamples: int = 1000) -> list[float]:
    """Bootstrap subjects, each already averaging its five repeated OOF errors."""
    if len(subject_differences) < 2 or not np.isfinite(subject_differences).all():
        raise ValueError("Paired subject differences are invalid")
    rng = np.random.default_rng(seed)
    means = np.empty(n_resamples, dtype=float)
    for index in range(n_resamples):
        means[index] = float(subject_differences[rng.integers(0, len(subject_differences), len(subject_differences))].mean())
    return [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))]


def weighted_calibration(y: np.ndarray, scores: np.ndarray, weights: np.ndarray) -> dict[str, float]:
    """Descriptive IPCW-weighted logistic recalibration on one OOF repeat."""
    if y.shape != scores.shape or y.shape != weights.shape:
        raise ValueError("Calibration arrays have different shapes")
    known = weights > 0
    if np.unique(y[known]).size < 2:
        raise ValueError("Known outcomes lack both classes")
    clipped = np.clip(scores[known], 1e-6, 1 - 1e-6)
    logits = np.log(clipped / (1 - clipped)).reshape(-1, 1)
    model = LogisticRegression(C=1e6, max_iter=3000, random_state=SEED)
    model.fit(logits, y[known], sample_weight=weights[known])
    return {"intercept": float(model.intercept_[0]), "slope": float(model.coef_[0, 0])}


def sigmoid(x: np.ndarray) -> np.ndarray:
    positive = x >= 0
    out = np.empty_like(x, dtype=float)
    out[positive] = 1 / (1 + np.exp(-x[positive]))
    exp_x = np.exp(x[~positive])
    out[~positive] = exp_x / (1 + exp_x)
    return out


def logit(p: np.ndarray) -> np.ndarray:
    q = np.clip(p, EPS, 1 - EPS)
    return np.log(q / (1 - q))


def recalibrate_cif(ad: np.ndarray, other: np.ndarray,
                    intercept: np.ndarray | float) -> tuple[np.ndarray, np.ndarray]:
    """Reweight AD versus non-AD while preserving the competing-risk simplex."""
    ad = np.asarray(ad, dtype=float)
    other = np.asarray(other, dtype=float)
    if (not np.isfinite(ad).all() or not np.isfinite(other).all()
            or (ad < 0).any() or (other < 0).any() or (ad + other > 1.000001).any()):
        raise ValueError("Invalid baseline cumulative incidences")
    ad_new = sigmoid(logit(ad) + intercept)
    other_new = other * (1 - ad_new) / np.maximum(1 - ad, EPS)
    if (ad_new + other_new > 1.000001).any() or (other_new < 0).any():
        raise ValueError("Recalibration violated competing-risk probability bounds")
    return ad_new, other_new


def calibration_description(test, scores, weights):
    target = test.event_type.eq(1).to_numpy(float)
    bins = []
    for number, (left, right) in enumerate(zip(BIN_EDGES[:-1], BIN_EDGES[1:])):
        selected = (scores >= left) & ((scores <= right) if number == len(BIN_EDGES)-2 else (scores < right))
        n = int(selected.sum())
        known = int(np.sum(selected & (weights > 0)))
        estimable = n > 0 and known >= MIN_KNOWN_PER_BIN
        observed = float(np.sum(weights[selected] * target[selected]) / n) if estimable else None
        bins.append({'lower': left, 'upper': right, 'subjects': n, 'known_outcomes': known,
                     'status': ('UNSTABLE_IPCW_RATE' if not 0 <= observed <= 1 else 'DESCRIPTIVE')
                               if estimable else 'LOW_SUPPORT',
                     'mean_predicted': float(scores[selected].mean()) if estimable else None,
                     'ipcw_ad_rate': observed})
    observed = float(np.sum(weights * target) / len(test))
    return {'method': 'train-KM IPCW Horvitz-Thompson rates, no recalibration fit or clipping',
            'overall_mean_prediction': float(scores.mean()), 'overall_ipcw_ad_rate': observed,
            'mean_prediction_minus_ipcw_rate': float(scores.mean() - observed), 'bins': bins}


def checked_inner(frame,seed):
    if frame.subject_id.duplicated().any():raise ExecutionError('DUPLICATE_INNER_SUBJECT')
    splits=list(StratifiedKFold(3,shuffle=True,random_state=seed).split(frame,frame.event_type))
    for a,b in splits:
        if set(frame.iloc[a].subject_id)&set(frame.iloc[b].subject_id):raise ExecutionError('INNER_SUBJECT_LEAKAGE')
        if not np.array_equal(np.unique(frame.iloc[a].event_type),[0,1,2]):raise ExecutionError('INNER_TRAINING_MISSING_CAUSE')
        known=(frame.iloc[b].event_type.ne(0)|frame.iloc[b].observed_month.eq(24))
        if frame.iloc[b].loc[known,'event_type'].eq(1).nunique()!=2:raise ExecutionError('INNER_CALIBRATION_MISSING_OUTCOME')
    if sorted(np.concatenate([b for _,b in splits]).tolist())!=list(range(len(frame))):
        raise ExecutionError('INCOMPLETE_INNER_COVERAGE')
    return splits


def calibrator_parameters(scores,outcome,weights):
    if (not np.isfinite(scores).all() or not np.isfinite(weights).all()
            or (scores<0).any() or (scores>1).any() or (weights<0).any()):
        raise ExecutionError('INVALID_CALIBRATION_INPUT')
    with warnings.catch_warnings():
        warnings.simplefilter('error',ConvergenceWarning)
        result=weighted_calibration(np.asarray(outcome),np.asarray(scores),np.asarray(weights))
    if not np.isfinite(list(result.values())).all() or result['slope']<=0:
        raise ExecutionError('NONMONOTONE_OR_INVALID_CALIBRATION')
    return result


def calibrated_values(ad,other,parameters):
    if (not np.isfinite(list(parameters.values())).all() or parameters['slope']<=0):
        raise ExecutionError('INVALID_CALIBRATOR_PARAMETERS')
    shift=parameters['intercept']+(parameters['slope']-1)*logit(np.asarray(ad))
    return recalibrate_cif(np.asarray(ad),np.asarray(other),shift)
