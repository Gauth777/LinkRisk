from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


TIME_COL = "TransactionDT"
WINDOW_1H = 60 * 60
WINDOW_24H = 24 * 60 * 60

# Strong keys remain the direct pseudo-entity links selected by the structural audit.
STRONG_KEYS = {
    "payment_device_profile": ["card1", "addr1", "DeviceInfo"],
    "payment_receiver_profile": ["card1", "addr1", "R_emaildomain"],
}

# payment_profile is deliberately NOT treated as a direct identity edge. It is
# used only as broad contextual history because its groups can be large.
CONTEXT_KEYS = {
    "payment_profile": ["card1", "card2", "card3", "card5", "addr1"],
}

# These exact pairs let us ask whether a recently seen payment profile is now
# appearing with a DeviceInfo / R_emaildomain value that has not previously
# been observed with that profile. They are comparison keys, not graph edges.
COMPARISON_KEYS = {
    "payment_profile_device_pair": [
        "card1", "card2", "card3", "card5", "addr1", "DeviceInfo"
    ],
    "payment_profile_rdomain_pair": [
        "card1", "card2", "card3", "card5", "addr1", "R_emaildomain"
    ],
}

ALL_KEYS = {**STRONG_KEYS, **CONTEXT_KEYS, **COMPARISON_KEYS}

RELATIONSHIP_MODEL_FEATURES = [
    "log_payment_profile_prior_1h",
    "log_payment_profile_prior_24h",
    "strong_device_prior_1h",
    "strong_receiver_prior_1h",
    "strong_device_prior_24h",
    "strong_receiver_prior_24h",
    "known_profile_new_deviceinfo",
    "known_profile_new_r_emaildomain",
    "strong_active_count",
    "comparison_available_count",
]


@dataclass
class KeyHistory:
    recent_1h: Deque[float]
    recent_24h: Deque[float]
    total_seen: int = 0


def _empty_history() -> KeyHistory:
    return KeyHistory(recent_1h=deque(), recent_24h=deque())


def make_composite_key(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise KeyError(f"Missing columns for relationship key: {missing}")

    complete = frame[columns].notna().all(axis=1)
    result = pd.Series(pd.NA, index=frame.index, dtype="string")
    if not complete.any():
        return result

    encoded = frame.loc[complete, columns].astype("string")
    combined = pd.Series("", index=encoded.index, dtype="string")
    for index, column in enumerate(columns):
        part = column + "=" + encoded[column]
        combined = part if index == 0 else combined + "|" + part

    result.loc[complete] = combined
    return result


def _snapshot(history: KeyHistory | None, timestamp: float) -> tuple[int, int, int]:
    if history is None:
        return 0, 0, 0

    cutoff_1h = timestamp - WINDOW_1H
    cutoff_24h = timestamp - WINDOW_24H

    while history.recent_1h and history.recent_1h[0] < cutoff_1h:
        history.recent_1h.popleft()
    while history.recent_24h and history.recent_24h[0] < cutoff_24h:
        history.recent_24h.popleft()

    return history.total_seen, len(history.recent_1h), len(history.recent_24h)


def build_relationship_features_v2(frame: pd.DataFrame) -> pd.DataFrame:
    """Build causal relationship features with broad context + strong links.

    Rows with the same TransactionDT are scored as one batch before any of them
    update history, so only strictly earlier transactions can influence a row.
    """
    if TIME_COL not in frame.columns:
        raise KeyError(f"{TIME_COL} is required")

    working = frame.copy()
    for name, columns in ALL_KEYS.items():
        working[name] = make_composite_key(working, columns)

    working = working.sort_values(TIME_COL, kind="mergesort")
    n = len(working)
    original_indices = working.index.to_numpy()
    timestamps = working[TIME_COL].to_numpy(dtype=float)
    key_arrays = {
        name: working[name].astype("object").to_numpy()
        for name in ALL_KEYS
    }

    histories: dict[str, dict[str, KeyHistory]] = {
        name: defaultdict(_empty_history) for name in ALL_KEYS
    }

    arrays: dict[str, np.ndarray] = {}
    for name in ALL_KEYS:
        arrays[f"{name}_available"] = np.zeros(n, dtype=np.int8)
        arrays[f"{name}_prior_total"] = np.zeros(n, dtype=np.int32)
        arrays[f"{name}_prior_1h"] = np.zeros(n, dtype=np.int32)
        arrays[f"{name}_prior_24h"] = np.zeros(n, dtype=np.int32)

    start = 0
    while start < n:
        timestamp = timestamps[start]
        end = start + 1
        while end < n and timestamps[end] == timestamp:
            end += 1

        # Read prior state first for every row at this exact timestamp.
        for pos in range(start, end):
            for name in ALL_KEYS:
                key = key_arrays[name][pos]
                if pd.isna(key):
                    continue

                arrays[f"{name}_available"][pos] = 1
                history = histories[name].get(str(key))
                total, prior_1h, prior_24h = _snapshot(history, timestamp)
                arrays[f"{name}_prior_total"][pos] = total
                arrays[f"{name}_prior_1h"][pos] = prior_1h
                arrays[f"{name}_prior_24h"][pos] = prior_24h

        # Only then add same-time rows to history.
        for pos in range(start, end):
            for name in ALL_KEYS:
                key = key_arrays[name][pos]
                if pd.isna(key):
                    continue

                history = histories[name][str(key)]
                cutoff_1h = timestamp - WINDOW_1H
                cutoff_24h = timestamp - WINDOW_24H
                while history.recent_1h and history.recent_1h[0] < cutoff_1h:
                    history.recent_1h.popleft()
                while history.recent_24h and history.recent_24h[0] < cutoff_24h:
                    history.recent_24h.popleft()
                history.recent_1h.append(timestamp)
                history.recent_24h.append(timestamp)
                history.total_seen += 1

        start = end

    out = pd.DataFrame(arrays, index=original_indices)

    profile_recent = out["payment_profile_prior_24h"] > 0
    strong_device = out["payment_device_profile_prior_24h"] > 0
    strong_receiver = out["payment_receiver_profile_prior_24h"] > 0

    device_comparable = (
        profile_recent & out["payment_profile_device_pair_available"].eq(1)
    )
    rdomain_comparable = (
        profile_recent & out["payment_profile_rdomain_pair_available"].eq(1)
    )

    out["known_profile_new_deviceinfo"] = (
        device_comparable & out["payment_profile_device_pair_prior_total"].eq(0)
    ).astype(np.int8)
    out["known_profile_new_r_emaildomain"] = (
        rdomain_comparable & out["payment_profile_rdomain_pair_prior_total"].eq(0)
    ).astype(np.int8)

    out["strong_device_prior_1h"] = (
        out["payment_device_profile_prior_1h"] > 0
    ).astype(np.int8)
    out["strong_receiver_prior_1h"] = (
        out["payment_receiver_profile_prior_1h"] > 0
    ).astype(np.int8)
    out["strong_device_prior_24h"] = strong_device.astype(np.int8)
    out["strong_receiver_prior_24h"] = strong_receiver.astype(np.int8)
    out["strong_active_count"] = (
        out["strong_device_prior_24h"] + out["strong_receiver_prior_24h"]
    ).astype(np.int8)
    out["comparison_available_count"] = (
        device_comparable.astype(np.int8) + rdomain_comparable.astype(np.int8)
    ).astype(np.int8)

    out["log_payment_profile_prior_1h"] = np.log1p(
        out["payment_profile_prior_1h"].astype(float)
    )
    out["log_payment_profile_prior_24h"] = np.log1p(
        out["payment_profile_prior_24h"].astype(float)
    )

    # Confidence describes evidence quality, not fraud probability.
    # Broad recent profile history is weak context; exact strong-link history
    # contributes more. Comparison availability adds modest confidence because it
    # lets us evaluate whether the profile changed device/domain context.
    confidence = (
        0.25 * profile_recent.astype(float)
        + 0.125 * device_comparable.astype(float)
        + 0.125 * rdomain_comparable.astype(float)
        + 0.25 * strong_device.astype(float)
        + 0.25 * strong_receiver.astype(float)
    )
    out["graph_confidence_v2"] = confidence.clip(lower=0.0, upper=1.0)

    return out.reindex(frame.index)


def relationship_model_matrix(features: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in RELATIONSHIP_MODEL_FEATURES if c not in features.columns]
    if missing:
        raise KeyError(f"Missing relationship-model features: {missing}")
    return features[RELATIONSHIP_MODEL_FEATURES].astype(float)


def fit_relationship_risk_model(
    features: pd.DataFrame,
    labels: np.ndarray | pd.Series,
) -> Pipeline:
    """Fit a small interpretable graph-risk model on training history only."""
    y = np.asarray(labels, dtype=np.int8)
    confidence = features["graph_confidence_v2"].to_numpy(dtype=float)
    active = confidence > 0.0

    if active.sum() == 0 or len(np.unique(y[active])) < 2:
        raise ValueError("Need active relationship examples from both classes")

    pipeline = Pipeline(
        steps=[
            ("scale", StandardScaler()),
            (
                "logit",
                LogisticRegression(
                    class_weight="balanced",
                    max_iter=500,
                    solver="lbfgs",
                    random_state=42,
                ),
            ),
        ]
    )
    pipeline.fit(relationship_model_matrix(features).loc[active], y[active])
    return pipeline


def predict_relationship_risk(model: Pipeline, features: pd.DataFrame) -> np.ndarray:
    confidence = features["graph_confidence_v2"].to_numpy(dtype=float)
    active = confidence > 0.0
    scores = np.zeros(len(features), dtype=float)
    if active.any():
        x = relationship_model_matrix(features)
        scores[active] = model.predict_proba(x.loc[active])[:, 1]
    return scores


def relationship_model_coefficients(model: Pipeline) -> dict[str, float]:
    logit = model.named_steps["logit"]
    return {
        feature: float(coef)
        for feature, coef in zip(RELATIONSHIP_MODEL_FEATURES, logit.coef_[0])
    }
