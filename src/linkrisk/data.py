from pathlib import Path
import pandas as pd


def load_ieee_cis(data_dir):
    data_dir = Path(data_dir)
    tx_path = data_dir / "train_transaction.csv"
    id_path = data_dir / "train_identity.csv"
    if not tx_path.exists():
        raise FileNotFoundError(f"Missing {tx_path}")
    if not id_path.exists():
        raise FileNotFoundError(f"Missing {id_path}")
    return pd.read_csv(tx_path), pd.read_csv(id_path)


def chronological_split(df, time_col="TransactionDT", train_frac=0.70, val_frac=0.15):
    ordered = df.sort_values(time_col).reset_index(drop=True)
    n = len(ordered)
    a = int(n * train_frac)
    b = int(n * (train_frac + val_frac))
    return ordered.iloc[:a].copy(), ordered.iloc[a:b].copy(), ordered.iloc[b:].copy()
