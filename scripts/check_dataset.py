from pathlib import Path
import sys
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from sentinelgraph.data import load_ieee_cis, chronological_split
DATA_DIR=ROOT/"data"/"raw"
CANDIDATES=["card1","card2","card3","card4","card5","card6","addr1","addr2","P_emaildomain","R_emaildomain","DeviceType","DeviceInfo"]
def pct(x): return f"{100*x:.2f}%"
def main():
    print("\n=== SentinelGraph Dataset Audit ===\n")
    tx,ident=load_ieee_cis(DATA_DIR)
    print(f"Transactions: {len(tx):,}")
    print(f"Identity rows: {len(ident):,}")
    print(f"Transaction columns: {len(tx.columns):,}")
    print(f"Identity columns: {len(ident.columns):,}")
    print(f"Duplicate TransactionID: {tx['TransactionID'].duplicated().sum():,}")
    print(f"Fraud rows: {int(tx['isFraud'].sum()):,}")
    print(f"Fraud rate: {pct(tx['isFraud'].mean())}")
    print(f"TransactionDT range: {tx['TransactionDT'].min()} -> {tx['TransactionDT'].max()}")
    cov=tx['TransactionID'].isin(set(ident['TransactionID'])).mean()
    print(f"Transactions with identity row: {pct(cov)}")
    print("\n--- Chronological split ---")
    tr,va,te=chronological_split(tx)
    for name,f in [("train",tr),("validation",va),("test",te)]:
        print(f"{name:10s} rows={len(f):,} DT=[{f.TransactionDT.min()}, {f.TransactionDT.max()}] fraud={pct(f.isFraud.mean())}")
    merged=tx[["TransactionID"]].merge(ident,on="TransactionID",how="left")
    print("\n--- Candidate relationship fields ---")
    for c in CANDIDATES:
        s=tx[c] if c in tx.columns else merged[c] if c in merged.columns else None
        if s is None: continue
        nn=s.notna().sum(); uniq=s.nunique(dropna=True); rep=s[s.notna()].duplicated(keep=False).sum()
        print(f"{c:16s} coverage={pct(nn/len(s)):>7s} unique={uniq:>8,} repeated_rows={pct(rep/len(s)):>7s}")
    print("\n--- Feature families ---")
    allcols=list(tx.columns)+list(ident.columns)
    for prefix in ["C","D","M","V","id_"]:
        print(f"{prefix:4s}: {sum(c.startswith(prefix) for c in allcols)} columns")
    print("\nGO/NO-GO QUESTIONS")
    print("1. Fraud represented in every chronological split?")
    print("2. Identity coverage enough to test sparse/missing graph evidence?")
    print("3. Which repeated fields form defensible edges?")
    print("4. Which fields create meaningless giant components?")
    print("5. Can graph features be computed using past information only?\n")
if __name__=="__main__": main()
