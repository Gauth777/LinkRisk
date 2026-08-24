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
from linkrisk.expert_v4 import (
    GATE_GRID,
    confidence_gate_expert,
    fit_graph_augmented_expert,
    predict_graph_augmented_expert,
    relationship_feature_importance,
)
from linkrisk.relationship_features_v4 import build_relationship_features_v4

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


def segment_metrics(y: np.ndarray, predictions: np.ndarray, mask: np.ndarray) -> dict:
    rows = int(mask.sum())
    if rows == 0:
        return {"rows": 0, "frauds": 0, "recall": 0.0, "precision": 0.0, "fpr": 0.0}

    ys = y[mask]
    ps = predictions[mask]
    frauds = int((ys == 1).sum())
    tp = int(((ys == 1) & (ps == 1)).sum())
    fp = int(((ys == 0) & (ps == 1)).sum())
    tn = int(((ys == 0) & (ps == 0)).sum())
    positives = int((ps == 1).sum())
    return {
        "rows": rows,
        "frauds": frauds,
        "recall": tp / frauds if frauds else 0.0,
        "precision": tp / positives if positives else 0.0,
        "fpr": fp / (fp + tn) if (fp + tn) else 0.0,
    }


def main():
    print("\n=== LinkRisk v0.4 Graph-Augmented Expert ===\n")
    print("Frozen baseline: unchanged transaction-only XGBoost.")
    print("New expert: same raw evidence + richer strictly-causal relationship features.")
    print("Structural confidence gates expert influence; confidence=0 is exact fallback.")
    print("Validation selects only gate strength / operating threshold from a predeclared grid.")
    print("Held-out test remains untouched.\n")

    preprocessor = joblib.load(MODEL_DIR / "baseline_preprocessor.joblib")
    baseline_model = joblib.load(MODEL_DIR / "baseline_xgboost.joblib")
    with (RESULTS_DIR / "baseline_features.json").open("r", encoding="utf-8") as f:
        baseline_features = json.load(f)

    merged = load_required_data()
    train, validation, test = chronological_split(merged)
    del test
    development = pd.concat([train, validation], axis=0).sort_values(TIME_COL, kind="mergesort")

    print(f"Training rows:   {len(train):,}")
    print(f"Validation rows: {len(validation):,}")
    print("Building richer causal relationship state...")
    rel = build_relationship_features_v4(development)
    rel_train = rel.loc[train.index]
    rel_val = rel.loc[validation.index]

    print("Transforming frozen raw baseline representation...")
    train_matrix = np.asarray(
        preprocessor.transform(train[baseline_features]), dtype=np.float32
    )
    val_matrix = np.asarray(
        preprocessor.transform(validation[baseline_features]), dtype=np.float32
    )

    y_train = train[TARGET].astype(np.int8).to_numpy()
    y_val = validation[TARGET].astype(np.int8).to_numpy()

    print("Training graph-augmented XGBoost expert on training partition only...")
    expert_model = fit_graph_augmented_expert(train_matrix, rel_train, y_train)

    baseline_scores = baseline_model.predict_proba(val_matrix)[:, 1]
    expert_scores = predict_graph_augmented_expert(expert_model, val_matrix, rel_val)
    confidence = rel_val["graph_confidence_v4"].to_numpy(dtype=float)

    baseline_threshold = choose_threshold_for_fpr(y_val, baseline_scores, TARGET_FPR)
    baseline_metrics = evaluate_scores(y_val, baseline_scores, baseline_threshold)
    baseline_pred = (baseline_scores >= baseline_threshold).astype(np.int8)

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

    observable = confidence > 0.0
    high_confidence = confidence >= 0.50
    baseline_fn_mask = (y_val == 1) & (baseline_pred == 0)
    reachable_fn = int((baseline_fn_mask & observable).sum())

    print("\n=== v0.4 Relationship Observability ===")
    print(f"No relationship evidence:        {(~observable).mean():.2%}")
    print(f"Relationship-observable:         {observable.mean():.2%}")
    print(f"High-confidence (>=0.50):        {high_confidence.mean():.2%}")
    print(f"Mean graph confidence:           {confidence.mean():.4f}")
    print(
        f"Baseline FNs structurally reachable: {reachable_fn:,} / "
        f"{baseline_metrics['false_negatives']:,} "
        f"({reachable_fn / max(baseline_metrics['false_negatives'], 1):.2%})"
    )

    print("\n=== Predeclared Gate Grid @ <=1% Validation FPR ===")
    print(
        f"{'gate':>6s} {'threshold':>10s} {'precision':>10s} {'recall':>9s} "
        f"{'pr_auc':>9s} {'fpr':>9s} {'tp':>6s} {'fp':>6s}"
    )
    print("-" * 82)

    candidates = []
    score_by_gate: dict[float, np.ndarray] = {}
    for gate in GATE_GRID:
        fused = confidence_gate_expert(
            baseline_scores,
            expert_scores,
            confidence,
            gate,
        )
        score_by_gate[float(gate)] = fused
        threshold = choose_threshold_for_fpr(y_val, fused, TARGET_FPR)
        metrics = evaluate_scores(y_val, fused, threshold)
        metrics["gate_strength"] = float(gate)
        candidates.append(metrics)
        print(
            f"{gate:6.2f} {threshold:10.6f} {metrics['precision']:10.4f} "
            f"{metrics['recall']:9.4f} {metrics['pr_auc']:9.4f} "
            f"{metrics['false_positive_rate']:9.4%} "
            f"{metrics['true_positives']:6d} {metrics['false_positives']:6d}"
        )

    selected = max(candidates, key=lambda m: (m["recall"], m["pr_auc"]))
    selected_scores = score_by_gate[selected["gate_strength"]]
    selected_pred = (selected_scores >= selected["threshold"]).astype(np.int8)

    fallback = confidence == 0.0
    max_fallback_difference = float(
        np.max(np.abs(selected_scores[fallback] - baseline_scores[fallback]))
        if fallback.any()
        else 0.0
    )

    recovered_fn = int(((y_val == 1) & (baseline_pred == 0) & (selected_pred == 1)).sum())
    lost_tp = int(((y_val == 1) & (baseline_pred == 1) & (selected_pred == 0)).sum())
    removed_fp = int(((y_val == 0) & (baseline_pred == 1) & (selected_pred == 0)).sum())
    new_fp = int(((y_val == 0) & (baseline_pred == 0) & (selected_pred == 1)).sum())

    print("\n=== Selected v0.4 Development Configuration ===")
    print(f"Gate strength:         {selected['gate_strength']:.2f}")
    print(f"Threshold:             {selected['threshold']:.6f}")
    print(f"Precision:             {selected['precision']:.4f}")
    print(f"Recall:                {selected['recall']:.4f}")
    print(f"PR-AUC:                {selected['pr_auc']:.4f}")
    print(f"FPR:                   {selected['false_positive_rate']:.4%}")
    print(f"TP / FP:               {selected['true_positives']} / {selected['false_positives']}")
    print(f"Recall delta vs ML:    {selected['recall'] - baseline_metrics['recall']:+.4f}")
    print(f"PR-AUC delta vs ML:    {selected['pr_auc'] - baseline_metrics['pr_auc']:+.4f}")
    print(f"Exact fallback check:  {max_fallback_difference:.12f}")

    print("\n=== Decision Transitions vs Baseline ===")
    print(f"Recovered baseline FNs: {recovered_fn}")
    print(f"Lost baseline TPs:       {lost_tp}")
    print(f"Removed baseline FPs:    {removed_fp}")
    print(f"New false positives:     {new_fp}")

    print("\n=== Structurally Defined Segment Results ===")
    for label, mask in [
        ("relationship-observable", observable),
        ("high-confidence >=0.50", high_confidence),
    ]:
        base_seg = segment_metrics(y_val, baseline_pred, mask)
        link_seg = segment_metrics(y_val, selected_pred, mask)
        print(f"{label}:")
        print(
            f"  rows={base_seg['rows']:,} frauds={base_seg['frauds']:,} | "
            f"baseline recall={base_seg['recall']:.2%} precision={base_seg['precision']:.2%} "
            f"FPR={base_seg['fpr']:.2%}"
        )
        print(
            f"  LinkRisk recall={link_seg['recall']:.2%} precision={link_seg['precision']:.2%} "
            f"FPR={link_seg['fpr']:.2%}"
        )

    importances = relationship_feature_importance(expert_model)
    print("\n=== Top Relationship Features in Augmented Expert ===")
    for name, value in sorted(importances.items(), key=lambda item: item[1], reverse=True)[:12]:
        print(f"{name:42s} {value:.5f}")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(expert_model, MODEL_DIR / "graph_augmented_expert_v4.joblib")

    result = {
        "experiment": "linkrisk_graph_augmented_expert_v0.4",
        "test_evaluated": False,
        "target_fpr_budget": TARGET_FPR,
        "baseline": baseline_metrics,
        "observability": {
            "no_evidence": float((~observable).mean()),
            "observable": float(observable.mean()),
            "high_confidence": float(high_confidence.mean()),
            "mean_confidence": float(confidence.mean()),
            "reachable_baseline_false_negatives": reachable_fn,
        },
        "gate_grid": candidates,
        "selected": selected,
        "transitions": {
            "recovered_baseline_false_negatives": recovered_fn,
            "lost_baseline_true_positives": lost_tp,
            "removed_baseline_false_positives": removed_fp,
            "new_false_positives": new_fp,
        },
        "exact_fallback_max_abs_difference": max_fallback_difference,
        "relationship_feature_importance": importances,
    }
    with (RESULTS_DIR / "expert_v4_validation.json").open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print("\nSaved:")
    print("  artifacts/models/graph_augmented_expert_v4.joblib")
    print("  artifacts/results/expert_v4_validation.json")
    print("Held-out test remains untouched.\n")


if __name__ == "__main__":
    main()
