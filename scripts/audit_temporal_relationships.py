from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from linkrisk.data import chronological_split
from linkrisk.relationships import RELATIONSHIP_KEYS, build_temporal_relationship_features

DATA_DIR = ROOT / "data" / "raw"

TX_COLUMNS = [
    "TransactionID",
    "TransactionDT",
    "card1",
    "addr1",
    "R_emaildomain",
]
ID_COLUMNS = [
    "TransactionID",
    "DeviceInfo",
]


def load_relationship_data() -> pd.DataFrame:
    tx = pd.read_csv(
        DATA_DIR / "train_transaction.csv",
        usecols=lambda column: column in TX_COLUMNS,
        low_memory=False,
    )
    identity = pd.read_csv(
        DATA_DIR / "train_identity.csv",
        usecols=lambda column: column in ID_COLUMNS,
        low_memory=False,
    )
    return tx.merge(identity, on="TransactionID", how="left", validate="one_to_one")


def percentile_nonzero(series: pd.Series, percentile: float) -> float:
    values = series[series > 0].to_numpy()
    if len(values) == 0:
        return 0.0
    return float(np.percentile(values, percentile))


def main():
    print("\n=== LinkRisk Temporal Relationship Audit ===\n")
    print("Loading selected relationship fields...")
    merged = load_relationship_data()
    train, validation, test = chronological_split(merged)
    del validation, test

    print(f"Training rows only: {len(train):,}")
    print("Building prior-only temporal features. This may take a few minutes...\n")

    features = build_temporal_relationship_features(train)

    header = (
        f"{'relationship':28s} {'avail':>8s} {'seen':>8s} "
        f"{'1h>0':>8s} {'24h>0':>8s} {'p95-1h':>9s} "
        f"{'p95-24h':>10s} {'max24h':>9s}"
    )
    print(header)
    print("-" * len(header))

    for name in RELATIONSHIP_KEYS:
        available = features[f"{name}_available"] == 1
        prior_total = features[f"{name}_prior_total"]
        prior_1h = features[f"{name}_prior_1h"]
        prior_24h = features[f"{name}_prior_24h"]

        print(
            f"{name:28s} "
            f"{available.mean():8.2%} "
            f"{(prior_total > 0).mean():8.2%} "
            f"{(prior_1h > 0).mean():8.2%} "
            f"{(prior_24h > 0).mean():8.2%} "
            f"{percentile_nonzero(prior_1h, 95):9.1f} "
            f"{percentile_nonzero(prior_24h, 95):10.1f} "
            f"{int(prior_24h.max()):9d}"
        )

    print("\n--- Graph evidence coverage ---")
    coverage_counts = features["graph_key_coverage"].value_counts(normalize=True).sort_index()
    for value, fraction in coverage_counts.items():
        print(f"key coverage {value:.1f}: {fraction:.2%} of training rows")

    active_counts = features["graph_active_prior_keys"].value_counts(normalize=True).sort_index()
    for value, fraction in active_counts.items():
        print(f"active prior keys {int(value)}: {fraction:.2%} of training rows")

    print("\n--- Aggregate temporal evidence ---")
    print(f"Any prior relationship within 1h:  {(features['graph_prior_1h_max'] > 0).mean():.2%}")
    print(f"Any prior relationship within 24h: {(features['graph_prior_24h_max'] > 0).mean():.2%}")
    print(f"Both selected keys have prior history: {features['graph_multi_key_prior'].mean():.2%}")
    print(f"Max prior-linked transactions in 1h:  {int(features['graph_prior_1h_max'].max())}")
    print(f"Max prior-linked transactions in 24h: {int(features['graph_prior_24h_max'].max())}")

    print("\nInterpretation rule:")
    print("- We are not looking at fraud labels yet.")
    print("- We want enough prior evidence to be useful, without extreme burst counts dominating the heuristic.")
    print("- These distributions will set the graph-risk normalization and graph-confidence logic before validation labels are used.\n")


if __name__ == "__main__":
    main()
