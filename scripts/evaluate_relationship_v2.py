from __future__ import annotations

import json
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

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
from linkrisk.graph_scoring import ALPHA_GRID, fuse_scores
from linkrisk.relationships_v2 import (
    build_relationship_features_v2,
    fit_relationship_risk_model,
    predict_relationship_risk,
    relationship_model_coefficients,
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


def safe_rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def main():
    print("\n=== LinkRisk Relationship Intelligence v0.2 ===\n")
    print("Training graph-risk model on training history only.")
    print("Validation is used only for the predeclared alpha grid / operating threshold.")
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
    print("Building causal contextual + strong-link features...")
    relationship_features = build_relationship_features_v2(development)
    rel_train = relationship_features.loc[train.index]
    rel_val = relationship_features.loc[validation.index]

    y_train = train[TARGET].astype(np.int8).to_numpy()
    y_val = validation[TARGET].astype(np.int8).to_numpy()

    print("Fitting interpretable logistic relationship-risk model on training only...")
    relationship_model = fit_relationship_risk_model(rel_train, y_train)
    graph_risk = predict_relationship_risk(relationship_model, rel_val)
    confidence = rel_val["graph_confidence_v2"].to_numpy(dtype=float)

    validation_matrix = preprocessor.transform(validation[baseline_features])
    ml_scores = baseline_model.predict_proba(validation_matrix)[:, 1]
    baseline_threshold = choose_threshold_for_fpr(y_val, ml_scores, TARGET_FPR)
    baseline_metrics = evaluate_scores(y_val, ml_scores, baseline_threshold)
    baseline_pred = (ml_scores >= baseline_threshold).astype(np.int8)

    print("\n=== Baseline Recheck ===")
    print(f"Precision: {baseline_metrics['precision']:.4f}")
    print(f"Recall:    {baseline_metrics['recall']:.4f}")
    print(f"PR-AUC:    {baseline_metrics['pr_auc']:.4f}")
    print(f"FPR:       {baseline_metrics['false_positive_rate']:.4%}")

    active = confidence > 0.0
    context_only = active & rel_val["strong_active_count"].to_numpy().astype(int).__eq__(0)
    one_strong = rel_val["strong_active_count"].to_numpy() == 1
    two_strong = rel_val["strong_active_count"].to_numpy() == 2

    total_frauds = int(y_val.sum())
    baseline_fn_mask = (y_val == 1) & (baseline_pred == 0)
    baseline_fn = int(baseline_fn_mask.sum())
    active_frauds = int(((y_val == 1) & active).sum())
    reachable_fn = int((baseline_fn_mask & active).sum())

    print("\n=== v0.2 Evidence Coverage / Headroom ===")
    print(f"No relationship evidence:      {(~active).mean():.2%}")
    print(f"Context-only evidence:         {context_only.mean():.2%}")
    print(f"One strong direct key active:  {one_strong.mean():.2%}")
    print(f"Two strong direct keys active: {two_strong.mean():.2%}")
    print(f"Mean graph confidence:         {confidence.mean():.4f}")
    print(f"Frauds with graph evidence:    {active_frauds:,} / {total_frauds:,}")
    print(f"Baseline FNs reachable:        {reachable_fn:,} / {baseline_fn:,} ({safe_rate(reachable_fn, baseline_fn):.2%})")
    print(f"Oracle max recall delta:       +{safe_rate(reachable_fn, total_frauds):.2%}")

    overall_rate = float(y_val.mean())
    active_rate = float(y_val[active].mean()) if active.any() else 0.0
    if active.any() and len(np.unique(y_val[active])) == 2:
        active_ap = float(average_precision_score(y_val[active], graph_risk[active]))
    else:
        active_ap = 0.0

    print("\n=== Relationship-Risk Quality ===")
    print(f"Overall fraud prevalence:      {overall_rate:.4f}")
    print(f"Active fraud prevalence:       {active_rate:.4f} ({safe_rate(active_rate, overall_rate):.2f}x lift)")
    print(f"Graph-risk PR-AUC active only: {active_ap:.4f}")
    print(f"Ranking lift over active prior:{safe_rate(active_ap, active_rate):.2f}x")

    coefficients = relationship_model_coefficients(relationship_model)
    print("\n=== Standardized Relationship-Model Coefficients ===")
    for feature, coef in sorted(coefficients.items(), key=lambda item: abs(item[1]), reverse=True):
        print(f"{feature:38s} {coef:+.4f}")

    print("\n=== Predeclared Alpha Grid @ <=1% Validation FPR ===")
    print(f"{'alpha':>6s} {'threshold':>10s} {'precision':>10s} {'recall':>9s} {'pr_auc':>9s} {'fpr':>9s} {'tp':>6s} {'fp':>6s}")
    print("-" * 82)

    candidates = []
    fused_by_alpha: dict[float, np.ndarray] = {}
    for alpha in ALPHA_GRID:
        fused = fuse_scores(ml_scores, graph_risk, confidence, alpha)
        fused_by_alpha[float(alpha)] = fused
        threshold = choose_threshold_for_fpr(y_val, fused, TARGET_FPR)
        metrics = evaluate_scores(y_val, fused, threshold)
        metrics["alpha"] = float(alpha)
        candidates.append(metrics)
        print(
            f"{alpha:6.2f} {threshold:10.6f} {metrics['precision']:10.4f} "
            f"{metrics['recall']:9.4f} {metrics['pr_auc']:9.4f} "
            f"{metrics['false_positive_rate']:9.4%} "
            f"{metrics['true_positives']:6d} {metrics['false_positives']:6d}"
        )

    selected = max(candidates, key=lambda m: (m["recall"], m["pr_auc"]))
    selected_fused = fused_by_alpha[selected["alpha"]]
    fallback = confidence == 0.0
    max_fallback_difference = float(
        np.max(np.abs(selected_fused[fallback] - ml_scores[fallback]))
        if fallback.any()
        else 0.0
    )

    print("\n=== Selected v0.2 Development Configuration ===")
    print(f"Alpha:                {selected['alpha']:.2f}")
    print(f"Threshold:            {selected['threshold']:.6f}")
    print(f"Precision:            {selected['precision']:.4f}")
    print(f"Recall:               {selected['recall']:.4f}")
    print(f"PR-AUC:               {selected['pr_auc']:.4f}")
    print(f"FPR:                  {selected['false_positive_rate']:.4%}")
    print(f"TP / FP:              {selected['true_positives']} / {selected['false_positives']}")
    print(f"Recall delta vs ML:   {selected['recall'] - baseline_metrics['recall']:+.4f}")
    print(f"PR-AUC delta vs ML:   {selected['pr_auc'] - baseline_metrics['pr_auc']:+.4f}")
    print(f"Exact fallback check: {max_fallback_difference:.12f}")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(relationship_model, MODEL_DIR / "relationship_risk_v2.joblib")

    result = {
        "experiment": "linkrisk_relationship_v0.2",
        "test_evaluated": False,
        "target_fpr_budget": TARGET_FPR,
        "baseline": baseline_metrics,
        "coverage": {
            "no_evidence": float((~active).mean()),
            "context_only": float(context_only.mean()),
            "one_strong": float(one_strong.mean()),
            "two_strong": float(two_strong.mean()),
            "mean_confidence": float(confidence.mean()),
        },
        "headroom": {
            "frauds_with_evidence": active_frauds,
            "baseline_false_negatives_reachable": reachable_fn,
            "reachable_fn_share": safe_rate(reachable_fn, baseline_fn),
            "oracle_max_recall_delta": safe_rate(reachable_fn, total_frauds),
        },
        "relationship_risk": {
            "active_fraud_prevalence": active_rate,
            "active_pr_auc": active_ap,
            "coefficients": coefficients,
        },
        "alpha_grid": candidates,
        "selected": selected,
        "exact_fallback_max_abs_difference": max_fallback_difference,
    }
    with (RESULTS_DIR / "relationship_v2_validation.json").open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print("\nSaved:")
    print("  artifacts/models/relationship_risk_v2.joblib")
    print("  artifacts/results/relationship_v2_validation.json")
    print("Held-out test remains untouched.\n")


if __name__ == "__main__":
    main()
