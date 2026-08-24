from __future__ import annotations

import json
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from linkrisk.baseline import (
    BASE_RAW_FEATURES,
    ID_COL,
    TARGET,
    TIME_COL,
    choose_threshold_for_fpr,
    evaluate_scores,
    merge_transaction_identity,
)
from linkrisk.data import chronological_split
from linkrisk.fusion_v3 import BETA_GRID, fuse_signed_relationship_evidence
from linkrisk.relationships_v2 import (
    build_relationship_features_v2,
    fit_relationship_risk_model,
    predict_relationship_risk,
)

DATA_DIR = ROOT / "data" / "raw"
MODEL_DIR = ROOT / "artifacts" / "models"
RESULTS_DIR = ROOT / "artifacts" / "results"
TARGET_FPR = 0.01


def load_required_data() -> pd.DataFrame:
    tx_path = DATA_DIR / "train_transaction.csv"
    id_path = DATA_DIR / "train_identity.csv"

    required_tx = {ID_COL, TIME_COL, TARGET, *BASE_RAW_FEATURES}
    required_id = {ID_COL, *BASE_RAW_FEATURES}

    tx = pd.read_csv(
        tx_path,
        usecols=lambda c: c in required_tx,
        low_memory=False,
    )
    identity = pd.read_csv(
        id_path,
        usecols=lambda c: c in required_id,
        low_memory=False,
    )
    return merge_transaction_identity(tx, identity)


def transition_counts(y: np.ndarray, before: np.ndarray, after: np.ndarray) -> dict:
    return {
        "recovered_false_negatives": int(((y == 1) & (before == 0) & (after == 1)).sum()),
        "lost_true_positives": int(((y == 1) & (before == 1) & (after == 0)).sum()),
        "removed_false_positives": int(((y == 0) & (before == 1) & (after == 0)).sum()),
        "new_false_positives": int(((y == 0) & (before == 0) & (after == 1)).sum()),
    }


def main():
    print("\n=== LinkRisk v0.3 Signed Evidence Fusion ===\n")
    print("Relationship features/model: v0.2, trained on training history only.")
    print("Change under test: signed confidence-gated log-odds fusion.")
    print("Validation chooses beta / operating threshold from a predeclared grid.")
    print("Held-out test remains untouched.\n")

    preprocessor = joblib.load(MODEL_DIR / "baseline_preprocessor.joblib")
    baseline_model = joblib.load(MODEL_DIR / "baseline_xgboost.joblib")
    with (RESULTS_DIR / "baseline_features.json").open("r", encoding="utf-8") as f:
        baseline_features = json.load(f)

    merged = load_required_data()
    train, validation, test = chronological_split(merged)
    del test

    development = pd.concat([train, validation], axis=0).sort_values(
        TIME_COL, kind="mergesort"
    )

    print(f"Training rows:   {len(train):,}")
    print(f"Validation rows: {len(validation):,}")
    print("Building causal v0.2 relationship features...")
    relationship_features = build_relationship_features_v2(development)
    rel_train = relationship_features.loc[train.index]
    rel_val = relationship_features.loc[validation.index]

    y_train = train[TARGET].astype(np.int8).to_numpy()
    y_val = validation[TARGET].astype(np.int8).to_numpy()

    print("Fitting relationship-risk model on training only...")
    relationship_model = fit_relationship_risk_model(rel_train, y_train)
    relationship_scores = predict_relationship_risk(relationship_model, rel_val)
    confidence = rel_val["graph_confidence_v2"].to_numpy(dtype=float)

    validation_matrix = preprocessor.transform(validation[baseline_features])
    ml_scores = baseline_model.predict_proba(validation_matrix)[:, 1]
    baseline_threshold = choose_threshold_for_fpr(y_val, ml_scores, TARGET_FPR)
    baseline_metrics = evaluate_scores(y_val, ml_scores, baseline_threshold)
    baseline_pred = (ml_scores >= baseline_threshold).astype(np.int8)

    print("\n=== Frozen Baseline ===")
    print(f"Threshold: {baseline_threshold:.6f}")
    print(f"Precision: {baseline_metrics['precision']:.4f}")
    print(f"Recall:    {baseline_metrics['recall']:.4f}")
    print(f"PR-AUC:    {baseline_metrics['pr_auc']:.4f}")
    print(f"FPR:       {baseline_metrics['false_positive_rate']:.4%}")
    print(
        f"TP / FP / TN / FN: {baseline_metrics['true_positives']} / "
        f"{baseline_metrics['false_positives']} / {baseline_metrics['true_negatives']} / "
        f"{baseline_metrics['false_negatives']}"
    )

    print("\n=== Predeclared Beta Grid @ <=1% Validation FPR ===")
    print(
        f"{'beta':>6s} {'threshold':>10s} {'precision':>10s} {'recall':>9s} "
        f"{'pr_auc':>9s} {'fpr':>9s} {'tp':>6s} {'fp':>6s}"
    )
    print("-" * 82)

    candidates = []
    fused_by_beta: dict[float, np.ndarray] = {}
    for beta in BETA_GRID:
        fused = fuse_signed_relationship_evidence(
            ml_scores,
            relationship_scores,
            confidence,
            beta,
        )
        fused_by_beta[float(beta)] = fused
        threshold = choose_threshold_for_fpr(y_val, fused, TARGET_FPR)
        metrics = evaluate_scores(y_val, fused, threshold)
        metrics["beta"] = float(beta)
        candidates.append(metrics)
        print(
            f"{beta:6.2f} {threshold:10.6f} {metrics['precision']:10.4f} "
            f"{metrics['recall']:9.4f} {metrics['pr_auc']:9.4f} "
            f"{metrics['false_positive_rate']:9.4%} "
            f"{metrics['true_positives']:6d} {metrics['false_positives']:6d}"
        )

    selected = max(candidates, key=lambda m: (m["recall"], m["pr_auc"]))
    selected_fused = fused_by_beta[selected["beta"]]
    selected_pred = (selected_fused >= selected["threshold"]).astype(np.int8)
    transitions = transition_counts(y_val, baseline_pred, selected_pred)

    fallback = confidence == 0.0
    fallback_difference = float(
        np.max(np.abs(selected_fused[fallback] - ml_scores[fallback]))
        if fallback.any()
        else 0.0
    )

    active = confidence > 0.0
    if active.any():
        delta = selected_fused[active] - ml_scores[active]
        raised = int((delta > 1e-12).sum())
        lowered = int((delta < -1e-12).sum())
        unchanged = int(active.sum()) - raised - lowered
    else:
        raised = lowered = unchanged = 0

    print("\n=== Selected v0.3 Development Configuration ===")
    print(f"Beta:                 {selected['beta']:.2f}")
    print(f"Threshold:            {selected['threshold']:.6f}")
    print(f"Precision:            {selected['precision']:.4f}")
    print(f"Recall:               {selected['recall']:.4f}")
    print(f"PR-AUC:               {selected['pr_auc']:.4f}")
    print(f"FPR:                  {selected['false_positive_rate']:.4%}")
    print(f"TP / FP:              {selected['true_positives']} / {selected['false_positives']}")
    print(f"Recall delta vs ML:   {selected['recall'] - baseline_metrics['recall']:+.4f}")
    print(f"PR-AUC delta vs ML:   {selected['pr_auc'] - baseline_metrics['pr_auc']:+.4f}")
    print(f"Exact fallback check: {fallback_difference:.12f}")

    print("\n=== Decision Transitions vs Baseline ===")
    print(f"Recovered baseline FNs: {transitions['recovered_false_negatives']}")
    print(f"Lost baseline TPs:       {transitions['lost_true_positives']}")
    print(f"Removed baseline FPs:    {transitions['removed_false_positives']}")
    print(f"New false positives:     {transitions['new_false_positives']}")
    print(f"Graph-active scores raised:  {raised:,}")
    print(f"Graph-active scores lowered: {lowered:,}")
    print(f"Graph-active unchanged:      {unchanged:,}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    result = {
        "experiment": "linkrisk_signed_fusion_v0.3",
        "test_evaluated": False,
        "target_fpr_budget": TARGET_FPR,
        "baseline": baseline_metrics,
        "beta_grid": candidates,
        "selected": selected,
        "transitions": transitions,
        "active_score_direction": {
            "raised": raised,
            "lowered": lowered,
            "unchanged": unchanged,
        },
        "exact_fallback_max_abs_difference": fallback_difference,
    }
    with (RESULTS_DIR / "fusion_v3_validation.json").open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print("\nSaved artifacts/results/fusion_v3_validation.json")
    print("Held-out test remains untouched.\n")


if __name__ == "__main__":
    main()
