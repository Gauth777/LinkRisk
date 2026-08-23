from __future__ import annotations

import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from linkrisk.baseline import (
    BASE_RAW_FEATURES,
    ID_COL,
    TARGET,
    TIME_COL,
    merge_transaction_identity,
    save_baseline_artifacts,
    train_xgboost_baseline,
)
from linkrisk.data import chronological_split

DATA_DIR = ROOT / "data" / "raw"
MODEL_DIR = ROOT / "artifacts" / "models"
RESULTS_DIR = ROOT / "artifacts" / "results"
TARGET_FPR = 0.01


def load_baseline_columns():
    tx_path = DATA_DIR / "train_transaction.csv"
    id_path = DATA_DIR / "train_identity.csv"

    if not tx_path.exists() or not id_path.exists():
        raise FileNotFoundError(
            "Expected train_transaction.csv and train_identity.csv under data/raw/"
        )

    required_transaction = {ID_COL, TIME_COL, TARGET, *BASE_RAW_FEATURES}
    required_identity = {ID_COL, *BASE_RAW_FEATURES}

    transactions = pd.read_csv(
        tx_path,
        usecols=lambda column: column in required_transaction,
        low_memory=False,
    )
    identity = pd.read_csv(
        id_path,
        usecols=lambda column: column in required_identity,
        low_memory=False,
    )
    return transactions, identity


def main():
    print("\n=== LinkRisk ML Baseline ===\n")
    print("Loading only frozen baseline columns...")
    transactions, identity = load_baseline_columns()

    if TARGET not in transactions.columns:
        raise ValueError("Training transaction file does not contain isFraud")

    merged = merge_transaction_identity(transactions, identity)
    train, validation, test = chronological_split(merged)

    print(f"Train rows:      {len(train):,}")
    print(f"Validation rows: {len(validation):,}")
    print(f"Sealed test rows:{len(test):,}")
    print(f"Train fraud rate:      {train[TARGET].mean():.4%}")
    print(f"Validation fraud rate: {validation[TARGET].mean():.4%}")
    print("Test labels are not evaluated in this script.\n")

    print("Training XGBoost transaction-only baseline...")
    artifacts = train_xgboost_baseline(
        train,
        validation,
        target_fpr=TARGET_FPR,
    )

    save_baseline_artifacts(artifacts, MODEL_DIR)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    result = {
        "experiment": "ml_only_baseline_v0.1",
        "split": "chronological_70_15_15",
        "test_evaluated": False,
        "target_fpr_budget": TARGET_FPR,
        "train_rows": len(train),
        "validation_rows": len(validation),
        "sealed_test_rows": len(test),
        "train_fraud_rate": float(train[TARGET].mean()),
        "validation_fraud_rate": float(validation[TARGET].mean()),
        "feature_columns": artifacts.feature_columns,
        "metrics": artifacts.metrics,
    }

    with (RESULTS_DIR / "baseline_validation.json").open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    with (RESULTS_DIR / "baseline_features.json").open("w", encoding="utf-8") as f:
        json.dump(artifacts.feature_columns, f, indent=2)

    m = artifacts.metrics
    print("\n=== Validation Result ===")
    print(f"Features:            {m['feature_count']}")
    print(f"Class weight:        {m['scale_pos_weight']:.3f}")
    print(f"Operating threshold: {m['threshold']:.6f}")
    print(f"Precision:           {m['precision']:.4f}")
    print(f"Recall:              {m['recall']:.4f}")
    print(f"PR-AUC:              {m['pr_auc']:.4f}")
    print(f"False positive rate: {m['false_positive_rate']:.4%}")
    print(f"TP / FP / TN / FN:   {m['true_positives']} / {m['false_positives']} / {m['true_negatives']} / {m['false_negatives']}")

    print("\nSaved:")
    print("  artifacts/models/baseline_preprocessor.joblib")
    print("  artifacts/models/baseline_xgboost.joblib")
    print("  artifacts/results/baseline_validation.json")
    print("  artifacts/results/baseline_features.json")
    print("\nIMPORTANT: do not evaluate the held-out test set yet.\n")


if __name__ == "__main__":
    main()
