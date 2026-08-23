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
from linkrisk.graph_scoring import ALPHA_GRID, add_graph_scores, fuse_scores
from linkrisk.relationships import build_temporal_relationship_features

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


def main():
    print("\n=== LinkRisk Graph-Augmented Validation ===\n")
    print("Loading frozen baseline model and required raw fields...")

    preprocessor = joblib.load(MODEL_DIR / "baseline_preprocessor.joblib")
    model = joblib.load(MODEL_DIR / "baseline_xgboost.joblib")

    feature_path = RESULTS_DIR / "baseline_features.json"
    with feature_path.open("r", encoding="utf-8") as f:
        baseline_features = json.load(f)

    merged = load_required_data()
    train, validation, test = chronological_split(merged)
    del test

    # Build temporal history over train + validation so validation transactions can
    # see all strictly-earlier training/validation events, but never test events.
    development = pd.concat([train, validation], axis=0).sort_values(
        TIME_COL, kind="mergesort"
    )

    print(f"Training-history rows: {len(train):,}")
    print(f"Validation rows:       {len(validation):,}")
    print("Held-out test partition remains untouched.\n")

    print("Building prior-only relationship features through validation...")
    temporal = build_temporal_relationship_features(development)
    graph = add_graph_scores(temporal)
    graph_val = graph.loc[validation.index]

    validation_matrix = preprocessor.transform(validation[baseline_features])
    ml_scores = model.predict_proba(validation_matrix)[:, 1]
    y_val = validation[TARGET].astype(np.int8).to_numpy()

    baseline_threshold = choose_threshold_for_fpr(y_val, ml_scores, TARGET_FPR)
    baseline_metrics = evaluate_scores(y_val, ml_scores, baseline_threshold)

    print("=== Baseline Recheck ===")
    print(f"Threshold: {baseline_threshold:.6f}")
    print(f"Precision: {baseline_metrics['precision']:.4f}")
    print(f"Recall:    {baseline_metrics['recall']:.4f}")
    print(f"PR-AUC:    {baseline_metrics['pr_auc']:.4f}")
    print(f"FPR:       {baseline_metrics['false_positive_rate']:.4%}\n")

    fallback_mask = graph_val["graph_confidence"].to_numpy() == 0.0
    print("=== Validation Graph Coverage ===")
    print(f"No prior graph evidence: {(fallback_mask.mean()):.2%}")
    print(f"One active key:          {(graph_val['graph_confidence'].eq(0.5).mean()):.2%}")
    print(f"Two active keys:         {(graph_val['graph_confidence'].eq(1.0).mean()):.2%}")
    print(f"Mean graph risk:         {graph_val['graph_risk'].mean():.4f}\n")

    candidates = []
    print("=== Predeclared Alpha Grid @ <=1% Validation FPR ===")
    print(f"{'alpha':>6s} {'threshold':>10s} {'precision':>10s} {'recall':>9s} {'pr_auc':>9s} {'fpr':>9s} {'tp':>6s} {'fp':>6s}")
    print("-" * 82)

    for alpha in ALPHA_GRID:
        fused = fuse_scores(
            ml_scores,
            graph_val["graph_risk"].to_numpy(),
            graph_val["graph_confidence"].to_numpy(),
            alpha,
        )
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

    # Highest recall at same FPR budget; PR-AUC breaks ties.
    selected = max(candidates, key=lambda m: (m["recall"], m["pr_auc"]))

    selected_fused = fuse_scores(
        ml_scores,
        graph_val["graph_risk"].to_numpy(),
        graph_val["graph_confidence"].to_numpy(),
        selected["alpha"],
    )
    max_fallback_difference = float(
        np.max(np.abs(selected_fused[fallback_mask] - ml_scores[fallback_mask]))
        if fallback_mask.any()
        else 0.0
    )

    print("\n=== Selected Development Configuration ===")
    print(f"Alpha:                {selected['alpha']:.2f}")
    print(f"Threshold:            {selected['threshold']:.6f}")
    print(f"Precision:            {selected['precision']:.4f}")
    print(f"Recall:               {selected['recall']:.4f}")
    print(f"PR-AUC:               {selected['pr_auc']:.4f}")
    print(f"FPR:                  {selected['false_positive_rate']:.4%}")
    print(f"Recall delta vs ML:   {selected['recall'] - baseline_metrics['recall']:+.4f}")
    print(f"PR-AUC delta vs ML:   {selected['pr_auc'] - baseline_metrics['pr_auc']:+.4f}")
    print(f"Exact-fallback check: max |fused-ML| when confidence=0 = {max_fallback_difference:.12f}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    result = {
        "experiment": "linkrisk_graph_validation_v0.1",
        "split": "validation_only_for_fusion_tuning",
        "test_evaluated": False,
        "target_fpr_budget": TARGET_FPR,
        "baseline": baseline_metrics,
        "alpha_grid": candidates,
        "selected": selected,
        "validation_graph_coverage": {
            "confidence_0": float(graph_val["graph_confidence"].eq(0.0).mean()),
            "confidence_0_5": float(graph_val["graph_confidence"].eq(0.5).mean()),
            "confidence_1": float(graph_val["graph_confidence"].eq(1.0).mean()),
            "mean_graph_risk": float(graph_val["graph_risk"].mean()),
        },
        "exact_fallback_max_abs_difference": max_fallback_difference,
    }

    with (RESULTS_DIR / "graph_validation.json").open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print("\nSaved artifacts/results/graph_validation.json")
    print("IMPORTANT: this is development/validation evidence, not the final held-out result.\n")


if __name__ == "__main__":
    main()
