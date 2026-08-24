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
from linkrisk.network_feedback_v6 import (
    GATE_GRID,
    build_network_feedback_v6,
    fit_network_specialist_v6,
    gate_network_scores,
    predict_network_specialist_v6,
    v6_feedback_feature_importance,
)
from linkrisk.relationship_features_v4 import build_relationship_features_v4

DATA_DIR = ROOT / "data" / "raw"
MODEL_DIR = ROOT / "artifacts" / "models"
RESULTS_DIR = ROOT / "artifacts" / "results"
TARGET_FPR = 0.01

V5_DEFAULT_RECALL = 0.3212
V5_DEFAULT_PR_AUC = 0.3887
MIN_RECALL_GAIN_TO_REPLACE = 0.0100
MIN_PR_AUC_GAIN_TO_REPLACE = 0.0100


def load_required_data() -> pd.DataFrame:
    tx_path = DATA_DIR / "train_transaction.csv"
    id_path = DATA_DIR / "train_identity.csv"
    required_tx = {ID_COL, TIME_COL, TARGET, *BASE_RAW_FEATURES}
    required_id = {ID_COL, *BASE_RAW_FEATURES}
    tx = pd.read_csv(tx_path, usecols=lambda c: c in required_tx, low_memory=False)
    identity = pd.read_csv(id_path, usecols=lambda c: c in required_id, low_memory=False)
    return merge_transaction_identity(tx, identity)


def segment_metrics(y: np.ndarray, pred: np.ndarray, mask: np.ndarray) -> dict:
    rows = int(mask.sum())
    if rows == 0:
        return {
            "rows": 0,
            "frauds": 0,
            "fraud_rate": 0.0,
            "recall": 0.0,
            "precision": 0.0,
            "fpr": 0.0,
        }
    ys = y[mask]
    ps = pred[mask]
    tp = int(((ys == 1) & (ps == 1)).sum())
    fp = int(((ys == 0) & (ps == 1)).sum())
    tn = int(((ys == 0) & (ps == 0)).sum())
    frauds = int((ys == 1).sum())
    positives = int((ps == 1).sum())
    return {
        "rows": rows,
        "frauds": frauds,
        "fraud_rate": float(ys.mean()),
        "recall": tp / frauds if frauds else 0.0,
        "precision": tp / positives if positives else 0.0,
        "fpr": fp / (fp + tn) if (fp + tn) else 0.0,
    }


def load_v5_champion() -> tuple[float, float]:
    path = RESULTS_DIR / "feedback_v5_validation.json"
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as f:
                result = json.load(f)
            selected = result.get("selected", {})
            return (
                float(selected.get("recall", V5_DEFAULT_RECALL)),
                float(selected.get("pr_auc", V5_DEFAULT_PR_AUC)),
            )
        except (OSError, ValueError, TypeError):
            pass
    return V5_DEFAULT_RECALL, V5_DEFAULT_PR_AUC


def main():
    print("\n=== LinkRisk v0.6 Temporal Fraud-Network Propagation ===\n")
    print("Final modelling challenger against frozen v0.5 champion.")
    print("Only training labels may enter fraud memory, after the fixed 72-hour delay.")
    print("Two-hop propagation uses strictly prior observed graph adjacency.")
    print("Validation labels never influence validation predictions.")
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
    print("Building causal unlabeled relationship state...")
    rel = build_relationship_features_v4(development)
    rel_train = rel.loc[train.index]
    rel_val = rel.loc[validation.index]

    print("Building delayed direct + two-hop fraud-network memory...")
    eligible = pd.Series(False, index=development.index)
    eligible.loc[train.index] = True
    fb = build_network_feedback_v6(development, eligible)
    fb_train = fb.loc[train.index]
    fb_val = fb.loc[validation.index]

    train_matrix = np.asarray(
        preprocessor.transform(train[baseline_features]), dtype=np.float32
    )
    val_matrix = np.asarray(
        preprocessor.transform(validation[baseline_features]), dtype=np.float32
    )
    y_train = train[TARGET].astype(np.int8).to_numpy()
    y_val = validation[TARGET].astype(np.int8).to_numpy()

    train_confidence = fb_train["feedback_confidence_v6"].to_numpy(dtype=float)
    train_active = train_confidence > 0.0
    print(
        f"Training network-active rows: {int(train_active.sum()):,} "
        f"({train_active.mean():.2%})"
    )
    print(f"Training active fraud rate:   {y_train[train_active].mean():.2%}\n")

    print("Training v0.6 network specialist on active training rows only...")
    specialist = fit_network_specialist_v6(
        train_matrix, rel_train, fb_train, y_train
    )

    baseline_scores = baseline_model.predict_proba(val_matrix)[:, 1]
    specialist_scores = predict_network_specialist_v6(
        specialist, val_matrix, rel_val, fb_val
    )
    confidence = fb_val["feedback_confidence_v6"].to_numpy(dtype=float)

    baseline_threshold = choose_threshold_for_fpr(
        y_val, baseline_scores, TARGET_FPR
    )
    baseline_metrics = evaluate_scores(
        y_val, baseline_scores, baseline_threshold
    )
    baseline_pred = (baseline_scores >= baseline_threshold).astype(np.int8)

    print("=== Frozen Baseline ===")
    print(f"Precision: {baseline_metrics['precision']:.4f}")
    print(f"Recall:    {baseline_metrics['recall']:.4f}")
    print(f"PR-AUC:    {baseline_metrics['pr_auc']:.4f}")
    print(f"FPR:       {baseline_metrics['false_positive_rate']:.4%}\n")

    direct_history = fb_val["feedback_history_channels"].to_numpy(dtype=float) > 0
    direct_fraud = fb_val["confirmed_fraud_channels"].to_numpy(dtype=float) > 0
    strong_direct_fraud = fb_val["any_strong_confirmed_fraud"].to_numpy(dtype=float) > 0
    two_hop_supported = fb_val["two_hop_supported_channels"].to_numpy(dtype=float) > 0
    two_hop_fraud = fb_val["two_hop_fraud_channels"].to_numpy(dtype=float) > 0
    two_hop_only_fraud = two_hop_fraud & ~direct_fraud
    multi_profile = fb_val["two_hop_multi_profile_corroboration"].to_numpy(dtype=float) > 0
    active = confidence > 0.0
    baseline_fn_mask = (y_val == 1) & (baseline_pred == 0)
    reachable = int((baseline_fn_mask & active).sum())

    print("=== v0.6 Network Observability ===")
    print(f"Any matured/propagated evidence: {active.mean():.2%}")
    print(f"Direct feedback history:        {direct_history.mean():.2%}")
    print(f"Direct confirmed-fraud channel: {direct_fraud.mean():.2%}")
    print(f"Strong direct fraud link:       {strong_direct_fraud.mean():.2%}")
    print(f"Two-hop supported context:      {two_hop_supported.mean():.2%}")
    print(f"Two-hop fraud propagation:      {two_hop_fraud.mean():.2%}")
    print(f"Two-hop-only fraud evidence:    {two_hop_only_fraud.mean():.2%}")
    print(f"Multi-profile corroboration:    {multi_profile.mean():.2%}")
    print(f"Mean confidence:                {confidence.mean():.4f}")
    if two_hop_fraud.any():
        print(f"Two-hop fraud segment rate:     {y_val[two_hop_fraud].mean():.2%}")
    if two_hop_only_fraud.any():
        print(f"Two-hop-only segment rate:      {y_val[two_hop_only_fraud].mean():.2%}")
    print(
        f"Baseline FNs reachable:         {reachable:,} / "
        f"{baseline_metrics['false_negatives']:,} "
        f"({reachable / max(baseline_metrics['false_negatives'], 1):.2%})\n"
    )

    print("=== Predeclared Gate Grid @ <=1% Validation FPR ===")
    print(
        f"{'gate':>6s} {'threshold':>10s} {'precision':>10s} {'recall':>9s} "
        f"{'pr_auc':>9s} {'fpr':>9s} {'tp':>6s} {'fp':>6s}"
    )
    print("-" * 82)
    candidates = []
    score_by_gate: dict[float, np.ndarray] = {}
    for gate in GATE_GRID:
        fused = gate_network_scores(
            baseline_scores, specialist_scores, confidence, gate
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

    selected = max(candidates, key=lambda item: (item["recall"], item["pr_auc"]))
    selected_scores = score_by_gate[selected["gate_strength"]]
    selected_pred = (selected_scores >= selected["threshold"]).astype(np.int8)
    fallback = confidence == 0.0
    fallback_error = float(
        np.max(np.abs(selected_scores[fallback] - baseline_scores[fallback]))
        if fallback.any()
        else 0.0
    )

    recovered_fn = int(
        ((y_val == 1) & (baseline_pred == 0) & (selected_pred == 1)).sum()
    )
    lost_tp = int(
        ((y_val == 1) & (baseline_pred == 1) & (selected_pred == 0)).sum()
    )
    removed_fp = int(
        ((y_val == 0) & (baseline_pred == 1) & (selected_pred == 0)).sum()
    )
    new_fp = int(
        ((y_val == 0) & (baseline_pred == 0) & (selected_pred == 1)).sum()
    )

    print("\n=== Selected v0.6 Development Configuration ===")
    print(f"Gate strength:         {selected['gate_strength']:.2f}")
    print(f"Threshold:             {selected['threshold']:.6f}")
    print(f"Precision:             {selected['precision']:.4f}")
    print(f"Recall:                {selected['recall']:.4f}")
    print(f"PR-AUC:                {selected['pr_auc']:.4f}")
    print(f"FPR:                   {selected['false_positive_rate']:.4%}")
    print(f"TP / FP:               {selected['true_positives']} / {selected['false_positives']}")
    print(f"Recall delta vs ML:    {selected['recall'] - baseline_metrics['recall']:+.4f}")
    print(f"PR-AUC delta vs ML:    {selected['pr_auc'] - baseline_metrics['pr_auc']:+.4f}")
    print(f"Exact fallback check:  {fallback_error:.12f}")

    print("\n=== Decision Transitions vs Baseline ===")
    print(f"Recovered baseline FNs: {recovered_fn}")
    print(f"Lost baseline TPs:       {lost_tp}")
    print(f"Removed baseline FPs:    {removed_fp}")
    print(f"New false positives:     {new_fp}")

    print("\n=== Network-Defined Segment Results ===")
    segment_definitions = [
        ("direct-confirmed-fraud", direct_fraud),
        ("strong-direct-confirmed-fraud", strong_direct_fraud),
        ("two-hop-fraud-propagation", two_hop_fraud),
        ("two-hop-only-fraud-evidence", two_hop_only_fraud),
        ("multi-profile-corroboration", multi_profile),
    ]
    segment_results = {}
    for label, mask in segment_definitions:
        base = segment_metrics(y_val, baseline_pred, mask)
        link = segment_metrics(y_val, selected_pred, mask)
        segment_results[label] = {"baseline": base, "linkrisk": link}
        print(f"{label}:")
        print(
            f"  rows={base['rows']:,} frauds={base['frauds']:,} "
            f"fraud_rate={base['fraud_rate']:.2%}"
        )
        print(
            f"  baseline recall={base['recall']:.2%} precision={base['precision']:.2%} "
            f"FPR={base['fpr']:.2%}"
        )
        print(
            f"  LinkRisk recall={link['recall']:.2%} precision={link['precision']:.2%} "
            f"FPR={link['fpr']:.2%}"
        )

    importances = v6_feedback_feature_importance(specialist)
    print("\n=== Top v0.6 Fraud-Memory / Network Features ===")
    for name, value in sorted(
        importances.items(), key=lambda item: item[1], reverse=True
    )[:15]:
        print(f"{name:46s} {value:.5f}")

    v5_recall, v5_pr_auc = load_v5_champion()
    recall_gain_v5 = selected["recall"] - v5_recall
    pr_auc_gain_v5 = selected["pr_auc"] - v5_pr_auc
    keep_v6 = bool(
        selected["false_positive_rate"] <= TARGET_FPR
        and (
            recall_gain_v5 >= MIN_RECALL_GAIN_TO_REPLACE
            or (
                pr_auc_gain_v5 >= MIN_PR_AUC_GAIN_TO_REPLACE
                and selected["recall"] >= v5_recall
            )
        )
    )

    print("\n=== Champion Decision Gate ===")
    print(f"v0.5 champion recall:  {v5_recall:.4f}")
    print(f"v0.6 recall gain:      {recall_gain_v5:+.4f}")
    print(f"v0.5 champion PR-AUC:  {v5_pr_auc:.4f}")
    print(f"v0.6 PR-AUC gain:      {pr_auc_gain_v5:+.4f}")
    print(
        "Decision:               "
        + ("PROMOTE v0.6" if keep_v6 else "KEEP v0.5")
    )
    print("This decision rule was fixed before observing v0.6 validation results.")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(specialist, MODEL_DIR / "network_specialist_v6.joblib")

    result = {
        "experiment": "linkrisk_temporal_fraud_network_v0.6",
        "test_evaluated": False,
        "target_fpr_budget": TARGET_FPR,
        "baseline": baseline_metrics,
        "observability": {
            "active": float(active.mean()),
            "direct_history": float(direct_history.mean()),
            "direct_fraud": float(direct_fraud.mean()),
            "strong_direct_fraud": float(strong_direct_fraud.mean()),
            "two_hop_supported": float(two_hop_supported.mean()),
            "two_hop_fraud": float(two_hop_fraud.mean()),
            "two_hop_only_fraud": float(two_hop_only_fraud.mean()),
            "multi_profile": float(multi_profile.mean()),
            "mean_confidence": float(confidence.mean()),
            "reachable_baseline_false_negatives": reachable,
        },
        "gate_grid": candidates,
        "selected": selected,
        "transitions": {
            "recovered_baseline_false_negatives": recovered_fn,
            "lost_baseline_true_positives": lost_tp,
            "removed_baseline_false_positives": removed_fp,
            "new_false_positives": new_fp,
        },
        "segments": segment_results,
        "feature_importance": importances,
        "exact_fallback_max_abs_difference": fallback_error,
        "champion_gate": {
            "v5_recall": v5_recall,
            "v5_pr_auc": v5_pr_auc,
            "recall_gain": recall_gain_v5,
            "pr_auc_gain": pr_auc_gain_v5,
            "min_recall_gain": MIN_RECALL_GAIN_TO_REPLACE,
            "min_pr_auc_gain": MIN_PR_AUC_GAIN_TO_REPLACE,
            "promote_v6": keep_v6,
        },
    }
    with (RESULTS_DIR / "network_v6_validation.json").open(
        "w", encoding="utf-8"
    ) as f:
        json.dump(result, f, indent=2)

    print("\nSaved:")
    print("  artifacts/models/network_specialist_v6.joblib")
    print("  artifacts/results/network_v6_validation.json")
    print("Held-out test remains untouched.\n")


if __name__ == "__main__":
    main()
