from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from linkrisk.data import chronological_split

DATA_DIR = ROOT / "data" / "raw"

TX_COLUMNS = [
    "TransactionID",
    "TransactionDT",
    "isFraud",
    "card1",
    "card2",
    "card3",
    "card5",
    "addr1",
    "P_emaildomain",
    "R_emaildomain",
]

ID_COLUMNS = [
    "TransactionID",
    "DeviceInfo",
    "DeviceType",
    "id_30",
    "id_31",
    "id_33",
]

# Candidate pseudo-entity definitions. These are relationship keys, not claims
# that the underlying records belong to the same real-world person/device.
CANDIDATE_KEYS = {
    "payment_core": ["card1", "addr1"],
    "payment_profile": ["card1", "card2", "card3", "card5", "addr1"],
    "payment_email_profile": ["card1", "addr1", "P_emaildomain"],
    "payment_receiver_profile": ["card1", "addr1", "R_emaildomain"],
    "identity_profile": ["DeviceInfo", "id_31"],
    "device_environment": ["DeviceInfo", "id_30", "id_31"],
    "device_display_profile": ["DeviceInfo", "id_33"],
    "payment_device_profile": ["card1", "addr1", "DeviceInfo"],
}


def load_columns() -> pd.DataFrame:
    tx_path = DATA_DIR / "train_transaction.csv"
    id_path = DATA_DIR / "train_identity.csv"

    tx = pd.read_csv(
        tx_path,
        usecols=lambda c: c in TX_COLUMNS,
        low_memory=False,
    )
    identity = pd.read_csv(
        id_path,
        usecols=lambda c: c in ID_COLUMNS,
        low_memory=False,
    )

    return tx.merge(identity, on="TransactionID", how="left", validate="one_to_one")


def make_key(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    available = [c for c in columns if c in frame.columns]
    if len(available) != len(columns):
        missing = sorted(set(columns) - set(available))
        raise KeyError(f"Missing columns for relationship key: {missing}")

    complete = frame[available].notna().all(axis=1)
    key = pd.Series(pd.NA, index=frame.index, dtype="string")

    # Prefix each field name so different composite definitions cannot collide.
    encoded = frame.loc[complete, available].astype("string")
    parts = []
    for column in available:
        parts.append(column + "=" + encoded[column])

    combined = parts[0]
    for part in parts[1:]:
        combined = combined + "|" + part

    key.loc[complete] = combined
    return key


def summarize_key(frame: pd.DataFrame, name: str, columns: list[str]) -> dict:
    key = make_key(frame, columns)
    valid = key.dropna()

    coverage = len(valid) / len(frame)
    if valid.empty:
        return {
            "name": name,
            "columns": columns,
            "coverage": coverage,
            "unique": 0,
            "repeated_row_rate": 0.0,
            "singleton_row_rate": 0.0,
            "p50_group_size": 0,
            "p95_group_size": 0,
            "max_group_size": 0,
            "groups_ge_2": 0,
            "groups_ge_5": 0,
            "groups_ge_20": 0,
        }

    counts = valid.value_counts()
    row_group_sizes = valid.map(counts)

    repeated_row_rate = float((row_group_sizes >= 2).sum() / len(frame))
    singleton_row_rate = float((row_group_sizes == 1).sum() / len(frame))

    return {
        "name": name,
        "columns": columns,
        "coverage": float(coverage),
        "unique": int(counts.size),
        "repeated_row_rate": repeated_row_rate,
        "singleton_row_rate": singleton_row_rate,
        "p50_group_size": float(np.percentile(counts.to_numpy(), 50)),
        "p95_group_size": float(np.percentile(counts.to_numpy(), 95)),
        "max_group_size": int(counts.max()),
        "groups_ge_2": int((counts >= 2).sum()),
        "groups_ge_5": int((counts >= 5).sum()),
        "groups_ge_20": int((counts >= 20).sum()),
    }


def main():
    print("\n=== LinkRisk Relationship-Key Audit ===\n")
    print("Loading candidate relationship fields...")
    merged = load_columns()

    # Candidate key selection must use training history only. Validation and test
    # remain outside this structural design audit.
    train, validation, test = chronological_split(merged)
    del validation, test

    print(f"Audit rows (training partition only): {len(train):,}")
    print("No validation/test labels or group statistics are used here.\n")

    print(
        f"{'key':26s} {'coverage':>9s} {'repeat':>9s} {'unique':>9s} "
        f"{'p50':>6s} {'p95':>6s} {'max':>7s} {'g>=5':>7s} {'g>=20':>7s}"
    )
    print("-" * 103)

    for name, columns in CANDIDATE_KEYS.items():
        stats = summarize_key(train, name, columns)
        print(
            f"{name:26s} "
            f"{stats['coverage']:9.2%} "
            f"{stats['repeated_row_rate']:9.2%} "
            f"{stats['unique']:9,d} "
            f"{stats['p50_group_size']:6.1f} "
            f"{stats['p95_group_size']:6.1f} "
            f"{stats['max_group_size']:7,d} "
            f"{stats['groups_ge_5']:7,d} "
            f"{stats['groups_ge_20']:7,d}"
        )

    print("\nHow to read this:")
    print("- coverage: fraction of training transactions with every field needed for the key")
    print("- repeat: fraction of all training rows whose key appears at least twice")
    print("- p50/p95/max: distribution of group sizes among observed keys")
    print("- huge max/p95 values warn that a key is too broad and may create giant components")
    print("- very low repeat means the key is too specific to provide useful relationship history")
    print("\nSelection rule: prefer keys with useful repetition but bounded group sizes. Do not select keys based on fraud labels.\n")


if __name__ == "__main__":
    main()
