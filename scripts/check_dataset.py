from pathlib import Path
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from linkrisk.data import load_ieee_cis, chronological_split

DATA_DIR = ROOT / "data" / "raw"
CANDIDATES = [
    "card1", "card2", "card3", "card4", "card5", "card6",
    "addr1", "addr2", "P_emaildomain", "R_emaildomain",
    "DeviceType", "DeviceInfo",
]


def pct(x):
    return f"{100 * x:.2f}%"


def main():
    print("\n=== LinkRisk Dataset Audit ===\n")
    tx, ident = load_ieee_cis(DATA_DIR)

    print(f"Transactions: {len(tx):,}")
    print(f"Identity rows: {len(ident):,}")
    print(f"Transaction columns: {len(tx.columns):,}")
    print(f"Identity columns: {len(ident.columns):,}")
    print(f"Duplicate TransactionID: {tx['TransactionID'].duplicated().sum():,}")

    if "isFraud" not in tx.columns:
        raise ValueError(
            "The loaded transaction file has no 'isFraud' target. "
            "You appear to be using the IEEE-CIS Kaggle test split. "
            "LinkRisk training/audit requires the original train_transaction.csv "
            "together with train_identity.csv. Do not rename test_transaction.csv "
            "to train_transaction.csv."
        )

    print(f"Fraud rows: {int(tx['isFraud'].sum()):,}")
    print(f"Fraud rate: {pct(tx['isFraud'].mean())}")
    print(
        f"TransactionDT range: {tx['TransactionDT'].min()} "
        f"-> {tx['TransactionDT'].max()}"
    )

    identity_ids = set(ident["TransactionID"])
    coverage = tx["TransactionID"].isin(identity_ids).mean()
    print(f"Transactions with identity row: {pct(coverage)}")

    print("\n--- Chronological split ---")
    train, validation, test = chronological_split(tx)
    for name, frame in [
        ("train", train),
        ("validation", validation),
        ("test", test),
    ]:
        print(
            f"{name:10s} rows={len(frame):,} "
            f"DT=[{frame.TransactionDT.min()}, {frame.TransactionDT.max()}] "
            f"fraud={pct(frame.isFraud.mean())}"
        )

    merged = tx[["TransactionID"]].merge(
        ident, on="TransactionID", how="left"
    )

    print("\n--- Candidate relationship fields ---")
    for column in CANDIDATES:
        if column in tx.columns:
            series = tx[column]
        elif column in merged.columns:
            series = merged[column]
        else:
            continue

        non_null = series.notna().sum()
        unique = series.nunique(dropna=True)
        repeated = series[series.notna()].duplicated(keep=False).sum()
        print(
            f"{column:16s} "
            f"coverage={pct(non_null / len(series)):>7s} "
            f"unique={unique:>8,} "
            f"repeated_rows={pct(repeated / len(series)):>7s}"
        )

    print("\n--- Feature families ---")
    all_columns = list(tx.columns) + list(ident.columns)
    for prefix in ["C", "D", "M", "V", "id_"]:
        count = sum(column.startswith(prefix) for column in all_columns)
        print(f"{prefix:4s}: {count} columns")

    print("\nGO/NO-GO QUESTIONS")
    print("1. Fraud represented in every chronological split?")
    print("2. Identity coverage enough to test sparse/missing graph evidence?")
    print("3. Which repeated fields form defensible edges?")
    print("4. Which fields create meaningless giant components?")
    print("5. Can graph features be computed using past information only?\n")


if __name__ == "__main__":
    main()
