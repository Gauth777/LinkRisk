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
    merge_transaction_identity,
)
from linkrisk.data import chronological_split
from linkrisk.graph_scoring import add_graph_scores
from linkrisk.relationships import RELATIONSHIP_KEYS, build_temporal_relationship_features

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


def segment_stats(
    name: str,
    mask: np.ndarray,
    y: np.ndarray,
    ml_pred: np.ndarray,
) -> dict:
    rows = int(mask.sum())
    frauds = int(y[mask].sum()) if rows else 0
    baseline_tp = int(((y == 1) & (ml_pred == 1) & mask).sum())
    baseline_fn = int(((y == 1) & (ml_pred == 0) & mask).sum())
    return {
        "segment": name,
        "rows": rows,
        "coverage": safe_rate(rows, len(y)),
        "frauds": frauds,
        "fraud_rate": safe_rate(frauds, rows),
        "baseline_tp": baseline_tp,
        "baseline_fn": baseline_fn,
    }


def main():
    print("\n=== LinkRisk Graph Signal Diagnostic ===\n")
    print("This script diagnoses validation signal; it does not tune new parameters.")
    print("The held-out test partition remains untouched.\n")

    preprocessor = joblib.load(MODEL_DIR / "baseline_preprocessor.joblib")
    model = joblib.load(MODEL_DIR / "baseline_xgboost.joblib")

    with (RESULTS_DIR / "baseline_features.json").open("r", encoding="utf-8") as f:
        baseline_features = json.load(f)

    merged = load_required_data()
    train, validation, test = chronological_split(merged)
    del test

    development = pd.concat([train, validation], axis=0).sort_values(
        TIME_COL, kind="mergesort"
    )

    print("Building leakage-safe temporal history through validation...")
    temporal = build_temporal_relationship_features(development)
    graph = add_graph_scores(temporal)
    graph_val = graph.loc[validation.index]

    validation_matrix = preprocessor.transform(validation[baseline_features])
    ml_scores = model.predict_proba(validation_matrix)[:, 1]
    y = validation[TARGET].astype(np.int8).to_numpy()

    baseline_threshold = choose_threshold_for_fpr(y, ml_scores, TARGET_FPR)
    ml_pred = (ml_scores >= baseline_threshold).astype(np.int8)

    total_frauds = int(y.sum())
    baseline_tp = int(((y == 1) & (ml_pred == 1)).sum())
    baseline_fn = int(((y == 1) & (ml_pred == 0)).sum())
    overall_fraud_rate = float(y.mean())

    confidence = graph_val["graph_confidence"].to_numpy(dtype=float)
    graph_risk = graph_val["graph_risk"].to_numpy(dtype=float)
    active = confidence > 0.0

    active_frauds = int(((y == 1) & active).sum())
    active_baseline_fn = int(((y == 1) & (ml_pred == 0) & active).sum())
    oracle_recall_ceiling = safe_rate(baseline_tp + active_baseline_fn, total_frauds)
    max_recall_delta = safe_rate(active_baseline_fn, total_frauds)

    print("=== Baseline Error Headroom ===")
    print(f"Validation frauds:                 {total_frauds:,}")
    print(f"Baseline true positives:           {baseline_tp:,}")
    print(f"Baseline false negatives:          {baseline_fn:,}")
    print(f"Frauds with any graph evidence:    {active_frauds:,}")
    print(f"Baseline FNs with graph evidence:  {active_baseline_fn:,}")
    print(f"Share of baseline FNs reachable:   {safe_rate(active_baseline_fn, baseline_fn):.2%}")
    print(f"Current-representation max recall delta (oracle): +{max_recall_delta:.2%}")
    print(f"Current-representation oracle recall ceiling:    {oracle_recall_ceiling:.2%}\n")

    print("=== Fraud Enrichment by Graph Confidence ===")
    print(f"Overall validation fraud rate: {overall_fraud_rate:.2%}\n")
    print(f"{'segment':24s} {'rows':>8s} {'coverage':>9s} {'fraud':>7s} {'fraud_rate':>11s} {'lift':>7s} {'base_FN':>8s}")
    print("-" * 83)

    segments = [
        segment_stats("confidence = 0.0", confidence == 0.0, y, ml_pred),
        segment_stats("confidence = 0.5", confidence == 0.5, y, ml_pred),
        segment_stats("confidence = 1.0", confidence == 1.0, y, ml_pred),
        segment_stats("any graph evidence", active, y, ml_pred),
    ]

    for stats in segments:
        lift = safe_rate(stats["fraud_rate"], overall_fraud_rate)
        print(
            f"{stats['segment']:24s} {stats['rows']:8,d} {stats['coverage']:9.2%} "
            f"{stats['frauds']:7,d} {stats['fraud_rate']:11.2%} {lift:7.2f}x "
            f"{stats['baseline_fn']:8,d}"
        )

    print("\n=== Relationship-Key Signal ===")
    print(f"{'relationship':27s} {'prior24 rows':>12s} {'fraud_rate':>11s} {'lift':>7s} {'base_FN':>8s}")
    print("-" * 73)

    key_results = []
    for key in RELATIONSHIP_KEYS:
        mask = graph_val[f"{key}_prior_24h"].to_numpy() > 0
        stats = segment_stats(key, mask, y, ml_pred)
        lift = safe_rate(stats["fraud_rate"], overall_fraud_rate)
        key_results.append({**stats, "lift": lift})
        print(
            f"{key:27s} {stats['rows']:12,d} {stats['fraud_rate']:11.2%} "
            f"{lift:7.2f}x {stats['baseline_fn']:8,d}"
        )

    print("\n=== Does Graph Risk Rank Fraud Within Active Transactions? ===")
    if active.sum() and len(np.unique(y[active])) == 2:
        active_ap = average_precision_score(y[active], graph_risk[active])
        active_base_rate = float(y[active].mean())
        print(f"Active rows:                    {int(active.sum()):,}")
        print(f"Active fraud prevalence:        {active_base_rate:.4f}")
        print(f"Graph-risk PR-AUC (active only):{active_ap:.4f}")
        print(f"Ranking lift over active prior: {safe_rate(active_ap, active_base_rate):.2f}x")
    else:
        active_ap = None
        active_base_rate = float(y[active].mean()) if active.sum() else 0.0
        print("Insufficient active examples/classes for PR-AUC.")

    print("\n=== Fixed Graph-Risk Bands (active rows only) ===")
    bands = [
        ("(0.00, 0.25]", 0.00, 0.25),
        ("(0.25, 0.50]", 0.25, 0.50),
        ("(0.50, 0.75]", 0.50, 0.75),
        ("(0.75, 1.00]", 0.75, 1.00),
    ]
    print(f"{'risk band':16s} {'rows':>8s} {'frauds':>8s} {'fraud_rate':>11s} {'base_FN':>8s}")
    print("-" * 58)
    band_results = []
    for label, low, high in bands:
        mask = active & (graph_risk > low) & (graph_risk <= high)
        stats = segment_stats(label, mask, y, ml_pred)
        band_results.append(stats)
        print(
            f"{label:16s} {stats['rows']:8,d} {stats['frauds']:8,d} "
            f"{stats['fraud_rate']:11.2%} {stats['baseline_fn']:8,d}"
        )

    print("\nDecision guide:")
    print("- Low reachable-FN share -> relationship coverage is the bottleneck.")
    print("- Strong fraud enrichment but weak graph-risk PR-AUC -> scoring formula is the bottleneck.")
    print("- Strong active PR-AUC but tiny fusion gain -> fusion/operating-point interaction is the bottleneck.")
    print("- Little fraud enrichment -> selected pseudo-entities are weak and should be redesigned.")

    result = {
        "experiment": "graph_signal_diagnostic_v0.1",
        "test_evaluated": False,
        "validation_fraud_rate": overall_fraud_rate,
        "baseline": {
            "threshold": float(baseline_threshold),
            "frauds": total_frauds,
            "true_positives": baseline_tp,
            "false_negatives": baseline_fn,
        },
        "headroom": {
            "frauds_with_graph_evidence": active_frauds,
            "baseline_false_negatives_with_graph_evidence": active_baseline_fn,
            "reachable_false_negative_share": safe_rate(active_baseline_fn, baseline_fn),
            "oracle_max_recall_delta": max_recall_delta,
            "oracle_recall_ceiling": oracle_recall_ceiling,
        },
        "confidence_segments": segments,
        "relationship_keys": key_results,
        "active_graph_risk_pr_auc": None if active_ap is None else float(active_ap),
        "active_graph_base_rate": active_base_rate,
        "risk_bands": band_results,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with (RESULTS_DIR / "graph_signal_diagnostic.json").open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print("\nSaved artifacts/results/graph_signal_diagnostic.json")
    print("Held-out test remains untouched.\n")


if __name__ == "__main__":
    main()
