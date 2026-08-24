from __future__ import annotations

import numpy as np


# Small predeclared development grid. Beta controls the strength of signed
# relationship evidence in log-odds space; validation chooses one value.
BETA_GRID = [0.25, 0.50, 1.00, 1.50, 2.00]


def _logit(values: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    clipped = np.clip(values, eps, 1.0 - eps)
    return np.log(clipped / (1.0 - clipped))


def _sigmoid(values: np.ndarray) -> np.ndarray:
    out = np.empty_like(values, dtype=float)
    positive = values >= 0
    out[positive] = 1.0 / (1.0 + np.exp(-values[positive]))
    exp_values = np.exp(values[~positive])
    out[~positive] = exp_values / (1.0 + exp_values)
    return out


def fuse_signed_relationship_evidence(
    ml_scores: np.ndarray,
    relationship_scores: np.ndarray,
    confidence: np.ndarray,
    beta: float,
) -> np.ndarray:
    """Fuse ML and relationship evidence bidirectionally in log-odds space.

    Relationship model score 0.5 is neutral. Scores above 0.5 can raise risk;
    scores below 0.5 can lower risk. Confidence gates the magnitude.

    Because the relationship model is class-balanced rather than calibrated,
    this output is treated as a ranking/risk score, not a fraud probability.

    Exact fallback invariant: confidence == 0 -> output == ml_scores exactly.
    """
    ml = np.asarray(ml_scores, dtype=float)
    rel = np.asarray(relationship_scores, dtype=float)
    conf = np.asarray(confidence, dtype=float)

    if ml.shape != rel.shape or ml.shape != conf.shape:
        raise ValueError("ml_scores, relationship_scores, and confidence must align")
    if beta < 0.0:
        raise ValueError("beta must be non-negative")
    if np.any((conf < 0.0) | (conf > 1.0)):
        raise ValueError("confidence must lie in [0, 1]")

    ml_log_odds = _logit(ml)
    relationship_evidence = _logit(rel)  # 0.5 -> 0 signed evidence
    fused_log_odds = ml_log_odds + beta * conf * relationship_evidence
    fused = _sigmoid(fused_log_odds)

    # Enforce the product invariant exactly, not just to floating-point tolerance.
    fallback = conf == 0.0
    fused[fallback] = ml[fallback]
    return np.clip(fused, 0.0, 1.0)
