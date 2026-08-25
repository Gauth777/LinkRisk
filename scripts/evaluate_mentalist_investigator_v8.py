from __future__ import annotations

import json
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from linkrisk.baseline import BASE_RAW_FEATURES, ID_COL, TARGET, TIME_COL, merge_transaction_identity
from linkrisk.data import chronological_split
from linkrisk.mentalist_features_v7 import MENTALIST_FEATURES, build_mentalist_features_v7, clue_activations

DATA_DIR = ROOT / "data" / "raw"
MODEL_DIR = ROOT / "artifacts" / "models"
RESULTS_DIR = ROOT / "artifacts" / "results"

MIN_CLUE_FAMILIES = 2
VERIFY_BUDGETS = (0.0025, 0.0050, 0.0100, 0.0200)
PRIMARY_BUDGET = 0.0100
MIN_ENRICHMENT = 2.0
MIN_RECALL_RECOVERY = 0.015


def load_data() -> pd.DataFrame:
    tx_path = DATA_DIR / "train_transaction.csv"
    id_path = DATA_DIR / "train_identity.csv"
    required_tx = {ID_COL, TIME_COL, TARGET, *BASE_RAW_FEATURES}
    required_id = {ID_COL, *BASE_RAW_FEATURES}
    tx = pd.read_csv(tx_path, usecols=lambda c: c in required_tx, low_memory=False)
    identity = pd.read_csv(id_path, usecols=lambda c: c in required_id, low_memory=False)
    return merge_transaction_identity(tx, identity)


def select_capacity(scores: np.ndarray, eligible: np.ndarray, budget_rows: int) -> tuple[np.ndarray, float | None]:
    selected = np.zeros(len(scores), dtype=bool)
    candidate_positions = np.flatnonzero(eligible)
    if budget_rows <= 0 or len(candidate_positions) == 0:
        return selected, None

    take = min(int(budget_rows), len(candidate_positions))
    candidate_scores = scores[candidate_positions]
    order = np.argsort(-candidate_scores, kind="mergesort")
    chosen = candidate_positions[order[:take]]
    selected[chosen] = True
    threshold = float(np.min(scores[chosen])) if len(chosen) else None
    return selected, threshold


def evaluate_budget(
    *,
    budget: float,
    y: np.ndarray,
    baseline_review: np.ndarray,
    jane_scores: np.ndarray,
    eligible: np.ndarray,
) -> dict:
    target_rows = int(round(len(y) * budget))
    verify, threshold = select_capacity(jane_scores, eligible, target_rows)

    frauds = int(((y == 1) & verify).sum())
    legitimate = int(((y == 0) & verify).sum())
    verify_rows = int(verify.sum())
    total_frauds = int((y == 1).sum())
    total_legitimate = int((y == 0).sum())
    base_rate = total_frauds / len(y)

    combined = baseline_review | verify
    combined_frauds = int(((y == 1) & combined).sum())
    combined_legitimate = int(((y == 0) & combined).sum())

    return {
        "budget": float(budget),
        "target_rows": target_rows,
        "verify_rows": verify_rows,
        "jane_score_threshold": threshold,
        "verify_frauds": frauds,
        "verify_legitimate": legitimate,
        "verify_fraud_rate": frauds / verify_rows if verify_rows else 0.0,
        "fraud_rate_enrichment": (frauds / verify_rows) / base_rate if verify_rows and base_rate else 0.0,
        "incremental_recall": frauds / total_frauds if total_frauds else 0.0,
        "incremental_legitimate_friction": legitimate / total_legitimate if total_legitimate else 0.0,
        "combined_intervention_rows": int(combined.sum()),
        "combined_fraud_capture": combined_frauds / total_frauds if total_frauds else 0.0,
        "combined_legitimate_friction": combined_legitimate / total_legitimate if total_legitimate else 0.0,
    }


def main() -> None:
    print("Loading IEEE-CIS development data...")
    data = load_data()
    train, validation, sealed_test = chronological_split(data)
    sealed_rows = len(sealed_test)
    del sealed_test
    del data

    with (RESULTS_DIR / "mentalist_v7_validation.json").open("r", encoding="utf-8") as f:
        v7 = json.load(f)
    with (RESULTS_DIR / "baseline_features.json").open("r", encoding="utf-8") as f:
        baseline_features = json.load(f)
    with (RESULTS_DIR / "baseline_validation.json").open("r", encoding="utf-8") as f:
        baseline_snapshot = json.load(f)

    mentalist = joblib.load(MODEL_DIR / "mentalist_v7_candidate.joblib")
    baseline_preprocessor = joblib.load(MODEL_DIR / "baseline_preprocessor.joblib")
    baseline_model = joblib.load(MODEL_DIR / "baseline_xgboost.joblib")

    print("Building causal proactive features for train -> validation...")
    development = pd.concat([train, validation], axis=0)
    proactive = build_mentalist_features_v7(development)
    val_proactive = proactive.loc[validation.index]
    del proactive
    del development

    clue_thresholds = v7["clue_thresholds"]
    clues = clue_activations(val_proactive, clue_thresholds)
    clue_count = clues["independent_clue_count"].to_numpy(dtype=int)

    val_raw = baseline_preprocessor.transform(validation[baseline_features])
    baseline_scores = baseline_model.predict_proba(val_raw)[:, 1]
    baseline_threshold = float(baseline_snapshot["metrics"]["threshold"])
    baseline_review = baseline_scores >= baseline_threshold

    x_val = val_proactive[MENTALIST_FEATURES].copy()
    x_val.insert(0, "baseline_oof_risk", baseline_scores)
    x_val = x_val.replace([np.inf, -np.inf], np.nan).fillna(0.0).astype(np.float32)
    jane_scores = mentalist.predict_proba(x_val)[:, 1]

    # Jane is a rescue investigator only. It cannot demote or replace baseline REVIEW.
    eligible = (~baseline_review) & (clue_count >= MIN_CLUE_FAMILIES)
    y = validation[TARGET].astype(np.int8).to_numpy()

    results = [
        evaluate_budget(
            budget=budget,
            y=y,
            baseline_review=baseline_review,
            jane_scores=jane_scores,
            eligible=eligible,
        )
        for budget in VERIFY_BUDGETS
    ]

    primary = next(row for row in results if abs(row["budget"] - PRIMARY_BUDGET) < 1e-12)
    useful = (
        primary["fraud_rate_enrichment"] >= MIN_ENRICHMENT
        and primary["incremental_recall"] >= MIN_RECALL_RECOVERY
    )

    base_frauds = int((y == 1).sum())
    base_legit = int((y == 0).sum())
    baseline_tp = int(((y == 1) & baseline_review).sum())
    baseline_fp = int(((y == 0) & baseline_review).sum())

    payload = {
        "experiment": "mentalist_v0.8_evidence_gated_investigator",
        "model": "mentalist_v7_candidate_reused_without_retraining",
        "held_out_test": {"status": "sealed", "rows": sealed_rows, "labels_used": False},
        "eligibility": {
            "min_independent_clue_families": MIN_CLUE_FAMILIES,
            "baseline_review_must_be_false": True,
            "eligible_rows": int(eligible.sum()),
            "eligible_share": float(eligible.mean()),
        },
        "baseline_review": {
            "threshold": baseline_threshold,
            "true_positives": baseline_tp,
            "false_positives": baseline_fp,
            "recall": baseline_tp / base_frauds,
            "legitimate_friction": baseline_fp / base_legit,
        },
        "verify_budgets": results,
        "usefulness_gate": {
            "primary_budget": PRIMARY_BUDGET,
            "min_fraud_rate_enrichment": MIN_ENRICHMENT,
            "min_incremental_recall": MIN_RECALL_RECOVERY,
            "pass": bool(useful),
        },
    }

    out = RESULTS_DIR / "mentalist_v8_investigator_validation.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("\n=== Mentalist v0.8 — Evidence-Gated Investigator ===")
    print("v0.7 remains a failed global replacement; this evaluates Jane only as a rescue VERIFY layer.")
    print("No confirmed-fraud memory is used. Held-out test remains sealed.\n")
    print(f"Eligible corroborated baseline-negative rows: {int(eligible.sum()):,} ({100*eligible.mean():.2f}% of validation)")
    print(f"Frozen baseline REVIEW: TP={baseline_tp} FP={baseline_fp} recall={baseline_tp/base_frauds:.4f}")

    for row in results:
        print(
            f"\nVERIFY budget {100*row['budget']:.2f}%"
            f"\n  rows:                {row['verify_rows']:,}"
            f"\n  frauds surfaced:     {row['verify_frauds']:,}"
            f"\n  legitimate surfaced: {row['verify_legitimate']:,}"
            f"\n  fraud rate:          {100*row['verify_fraud_rate']:.2f}%"
            f"\n  enrichment:          {row['fraud_rate_enrichment']:.2f}x"
            f"\n  incremental recall:  +{100*row['incremental_recall']:.2f} pp"
            f"\n  legit friction:      +{100*row['incremental_legitimate_friction']:.2f}%"
            f"\n  combined capture:    {100*row['combined_fraud_capture']:.2f}%"
            f"\n  combined friction:   {100*row['combined_legitimate_friction']:.2f}%"
        )

    print("\nUsefulness gate at 1.00% proactive VERIFY budget")
    print(f"  Required enrichment: >= {MIN_ENRICHMENT:.2f}x")
    print(f"  Required recovery:   >= +{100*MIN_RECALL_RECOVERY:.2f} pp recall")
    print(f"  Candidate status:    {'PASS' if useful else 'FAIL'}")
    print(f"\nSaved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
