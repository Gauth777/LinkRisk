from __future__ import annotations

import numpy as np
from xgboost import XGBClassifier

from linkrisk.relationship_features_v4 import RELATIONSHIP_FEATURES_V4, relationship_matrix_v4


GATE_GRID = [0.25, 0.50, 0.75, 1.00]


def fit_graph_augmented_expert(
    baseline_matrix: np.ndarray,
    relationship_features,
    labels: np.ndarray,
) -> XGBClassifier:
    """Train a graph-augmented expert on the same raw baseline representation plus causal relationship features."""
    raw = np.asarray(baseline_matrix, dtype=np.float32)
    graph = relationship_matrix_v4(relationship_features)
    x = np.hstack([raw, graph]).astype(np.float32, copy=False)
    y = np.asarray(labels, dtype=np.int8)

    negatives = int((y == 0).sum())
    positives = int((y == 1).sum())
    scale_pos_weight = negatives / max(positives, 1)

    model = XGBClassifier(
        objective="binary:logistic",
        eval_metric="aucpr",
        n_estimators=450,
        learning_rate=0.04,
        max_depth=5,
        min_child_weight=3,
        subsample=0.85,
        colsample_bytree=0.85,
        reg_lambda=1.5,
        reg_alpha=0.1,
        scale_pos_weight=scale_pos_weight,
        tree_method="hist",
        max_bin=128,
        n_jobs=-1,
        random_state=42,
    )
    model.fit(x, y, verbose=False)
    return model


def predict_graph_augmented_expert(
    model: XGBClassifier,
    baseline_matrix: np.ndarray,
    relationship_features,
) -> np.ndarray:
    raw = np.asarray(baseline_matrix, dtype=np.float32)
    graph = relationship_matrix_v4(relationship_features)
    x = np.hstack([raw, graph]).astype(np.float32, copy=False)
    return model.predict_proba(x)[:, 1]


def confidence_gate_expert(
    baseline_scores: np.ndarray,
    expert_scores: np.ndarray,
    confidence: np.ndarray,
    gate_strength: float,
) -> np.ndarray:
    """Blend the graph-aware expert toward the frozen baseline according to structural confidence.

    final = baseline + gate_strength * confidence * (expert - baseline)

    This allows the expert to raise or lower risk while preserving exact fallback
    whenever confidence is zero.
    """
    baseline = np.asarray(baseline_scores, dtype=float)
    expert = np.asarray(expert_scores, dtype=float)
    conf = np.asarray(confidence, dtype=float)

    if baseline.shape != expert.shape or baseline.shape != conf.shape:
        raise ValueError("baseline_scores, expert_scores, and confidence must align")
    if not 0.0 <= gate_strength <= 1.0:
        raise ValueError("gate_strength must lie in [0, 1]")
    if np.any((conf < 0.0) | (conf > 1.0)):
        raise ValueError("confidence must lie in [0, 1]")

    fused = baseline + gate_strength * conf * (expert - baseline)
    fallback = conf == 0.0
    fused[fallback] = baseline[fallback]
    return np.clip(fused, 0.0, 1.0)


def relationship_feature_importance(model: XGBClassifier) -> dict[str, float]:
    importances = np.asarray(model.feature_importances_, dtype=float)
    n_rel = len(RELATIONSHIP_FEATURES_V4)
    if importances.size < n_rel:
        return {}
    rel_importances = importances[-n_rel:]
    return {
        feature: float(value)
        for feature, value in zip(RELATIONSHIP_FEATURES_V4, rel_importances)
    }
