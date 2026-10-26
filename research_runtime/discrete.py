"""Discrete-time competing-risk CIF model for the future released ADNI cohort.

This module has no real-data CLI. Each month has mutually exclusive AD,
other-dementia, and event-free hazards. Formal training requires a reviewed
event-time contract, fold-contained preprocessing, and release verification.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


EVENT_TYPES = {0: "censored_or_admin_end", 1: "ad_dementia", 2: "other_dementia"}


def validate_contract(frame: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    needed = {"subject_id", "observed_month", "event_type", *features}
    if missing := needed - set(frame):
        raise ValueError(f"Competing-risk cohort missing fields: {sorted(missing)}")
    if frame.empty or frame.subject_id.isna().any() or frame.subject_id.duplicated().any():
        raise ValueError("One index record per subject is required")
    work = frame.copy()
    work["observed_month"] = pd.to_numeric(work.observed_month, errors="raise")
    work["event_type"] = pd.to_numeric(work.event_type, errors="raise")
    if (work.observed_month.isna().any() or not work.observed_month.between(1, 24).all()
            or not work.observed_month.eq(work.observed_month.astype(int)).all()):
        raise ValueError("observed_month must be an integer from 1 to 24")
    if work.event_type.isna().any() or not work.event_type.isin(EVENT_TYPES).all():
        raise ValueError("event_type must be 0, 1, or 2")
    for name in features:
        work[name] = pd.to_numeric(work[name], errors="raise")
    return work


def person_period(frame: pd.DataFrame, features: list[str]) -> tuple[pd.DataFrame, np.ndarray]:
    """Include complete observed months, with an event only in its final bin."""
    work = validate_contract(frame, features)
    repeated = work.loc[work.index.repeat(work.observed_month.astype(int))].copy()
    repeated["month"] = np.concatenate([np.arange(1, int(n) + 1) for n in work.observed_month])
    final_month = repeated["month"].eq(repeated["observed_month"])
    y = np.where(final_month, repeated["event_type"].to_numpy(dtype=int), 0)
    return repeated[[*features, "month"]].reset_index(drop=True), y


def make_estimator(features: list[str], seed: int = 20260926) -> Pipeline:
    numeric = Pipeline([
        ("impute", SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True)),
        ("scale", StandardScaler()),
    ])
    columns = ColumnTransformer([
        ("clinical", numeric, features),
        ("month", OneHotEncoder(handle_unknown="ignore"), ["month"]),
    ])
    return Pipeline([
        ("preprocess", columns),
        ("hazards", LogisticRegression(max_iter=3000, random_state=seed)),
    ])


def predict_cif(model: Pipeline, frame: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    """Return both cumulative incidences; their sum cannot exceed one."""
    work = frame[["subject_id", *features]].copy()
    if work.empty or work.subject_id.isna().any() or work.subject_id.duplicated().any():
        raise ValueError("Prediction input needs one row per subject")
    grid = work.loc[work.index.repeat(24)].copy()
    grid["month"] = np.tile(np.arange(1, 25), len(work))
    probabilities = model.predict_proba(grid[[*features, "month"]]).reshape(len(work), 24, -1)
    classes = model.named_steps["hazards"].classes_
    hazards = np.zeros((len(work), 24, 3), dtype=float)
    for index, cause in enumerate(classes):
        hazards[:, :, int(cause)] = probabilities[:, :, index]
    if (hazards < 0).any() or not np.isfinite(hazards).all():
        raise ValueError("Invalid predicted hazards")
    survival = np.ones(len(work), dtype=float)
    ad_cif = np.zeros(len(work), dtype=float)
    other_cif = np.zeros(len(work), dtype=float)
    for month in range(24):
        ad_cif += survival * hazards[:, month, 1]
        other_cif += survival * hazards[:, month, 2]
        survival *= hazards[:, month, 0]
    if (ad_cif + other_cif > 1.000001).any():
        raise ValueError("Predicted cumulative incidences exceed one")
    return pd.DataFrame({"subject_id": work.subject_id.astype(str).to_numpy(),
                         "ad_cif_24m": ad_cif, "other_dementia_cif_24m": other_cif})
