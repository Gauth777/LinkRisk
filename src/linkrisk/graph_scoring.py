from __future__ import annotations

import numpy as np
import pandas as pd


P95_1H = {
    "payment_device_profile": 4.0,
    "payment_receiver_profile": 4.0,
}

P95_24H = {
    "payment_device_profile": 6.0,
    "payment_receiver_profile": 7.0,
}

ALPHA_GRID = [0.10, 0.20, 0.30, 0.40]


def _clip01(values: pd.Series) -> pd.Series:
    return values.clip(lower=0.0, upper=1.0)


def add_graph_scores(features: pd.DataFrame) -> pd.DataFrame:
    """Add deterministic graph-risk and graph-confidence scores.

    Assumes prior-only temporal relationship features have already been built.
    No fraud labels are used here.
    """
    out = features.copy()
    key_scores: list[str] = []

    for key in P95_1H:
        one_hour = _clip01(out[f"{key}_prior_1h"].astype(float) / P95_1H[key])
        one_day = _clip01(out[f"{key}_prior_24h"].astype(float) / P95_24H[key])
        score_col = f"{key}_activity_score"
        out[score_col] = 0.60 * one_hour + 0.40 * one_day
        key_scores.append(score_col)

    out["graph_risk"] = out[key_scores].max(axis=1)

    active_keys = out["graph_active_prior_keys"].clip(lower=0, upper=2).astype(float)
    out["graph_confidence"] = active_keys / 2.0

    # With no prior relationship evidence, graph risk is forced to zero.
    no_prior = out["graph_confidence"] == 0.0
    out.loc[no_prior, "graph_risk"] = 0.0

    return out


def fuse_scores(
    ml_scores: np.ndarray | pd.Series,
    graph_risk: np.ndarray | pd.Series,
    graph_confidence: np.ndarray | pd.Series,
    alpha: float,
) -> np.ndarray:
    """Confidence-gated monotonic graph uplift.

    fused = ml + alpha * confidence * graph_risk * (1 - ml)

    Exact fallback property: confidence == 0 -> fused == ml.
    """
    ml = np.asarray(ml_scores, dtype=float)
    risk = np.asarray(graph_risk, dtype=float)
    confidence = np.asarray(graph_confidence, dtype=float)

    if not 0.0 <= alpha <= 1.0:
        raise ValueError("alpha must be between 0 and 1")

    fused = ml + alpha * confidence * risk * (1.0 - ml)
    return np.clip(fused, 0.0, 1.0)
