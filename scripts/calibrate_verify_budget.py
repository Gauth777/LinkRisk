from __future__ import annotations

import json
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from linkrisk.data import chronological_split
from linkrisk.decision import (
    CHAMPION_GATE_STRENGTH,
    MULTI_CHANNEL_CONFIDENCE,
    REVIEW_THRESHOLD,
    STRONG_EVIDENCE_CONFIDENCE,
)
from linkrisk.relationship_features_v4 import build_relationship_features_v4
from scripts.evaluate_feedback_v5 import (
    build_feedback,
    gate_scores,
    load_data,
    predict_specialist,
)

MODEL_DIR = ROOT / "artifacts" / "models"
RESULTS_DIR = ROOT / "artifacts" / "results"

# Business policy constraint fixed before calibration. This script does not use
# isFraud or any other validation label to select the VERIFY threshold.
TOTAL_INTERVENTION_BUDGET = 0.06


def main() -> None:
    print("\n=== LinkRisk VERIFY Budget Calibration ===\n")
    print(f"Total VERIFY + REVIEW budget: {TOTAL_INTERVENTION_BUDGET:.2%}")
    print(f"Frozen REVIEW threshold:      {REVIEW_THRESHOLD:.6f}")
    print("Calibration inputs: model scores + structural feedback evidence only.")
    print("Validation fraud labels are not used to select the threshold.")
    print("Held-out test remains untouched.\n")

    specialist_path = MODEL_DIR / "feedback_specialist_v5.joblib"
    if not specialist_path.exists():
        raise FileNotFoundError(
            "Missing artifacts/models/feedback_specialist_v5.joblib. "
            "Run scripts/evaluate_feedback_v5.py first."
        )

    preprocessor = joblib.load(MODEL_DIR / "baseline_preprocessor.joblib")
    baseline_model = joblib.load(MODEL_DIR / "baseline_xgboost.joblib")
    specialist_model = joblib.load(specialist_path)

    with (RESULTS_DIR / "baseline_features.json").open("r", encoding="utf-8") as f:
        baseline_features = json.load(f)

    merged = load_data()
    train, validation, test = chronological_split(merged)
    del test
    development = pd.concat([train, validation], axis=0).sort_values(
        "TransactionDT", kind="mergesort"
    )

    print(f"Training rows:   {len(train):,}")
    print(f"Validation rows: {len(validation):,}")
    print("Reconstructing frozen v0.5 state...")

    relationship = build_relationship_features_v4(development)
    rel_val = relationship.loc[validation.index]

    eligible = pd.Series(False, index=development.index)
    eligible.loc[train.index] = True
    feedback = build_feedback(development, eligible)
    fb_val = feedback.loc[validation.index]

    val_matrix = np.asarray(
        preprocessor.transform(validation[baseline_features]), dtype=np.float32
    )
    baseline_scores = baseline_model.predict_proba(val_matrix)[:, 1]
    specialist_scores = predict_specialist(
        specialist_model,
        val_matrix,
        rel_val,
        fb_val,
    )
    confidence = fb_val["feedback_confidence"].to_numpy(dtype=float)
    linkrisk_scores = gate_scores(
        baseline_scores,
        specialist_scores,
        confidence,
        CHAMPION_GATE_STRENGTH,
    )

    review = linkrisk_scores >= REVIEW_THRESHOLD

    strong_link = fb_val["any_strong_confirmed_fraud"].to_numpy(dtype=float) > 0.0
    fraud_channels = fb_val["confirmed_fraud_channels"].to_numpy(dtype=float)

    forced_strong = (
        (~review)
        & strong_link
        & (confidence >= STRONG_EVIDENCE_CONFIDENCE)
    )
    forced_multi = (
        (~review)
        & (~forced_strong)
        & (fraud_channels >= 2.0)
        & (confidence >= MULTI_CHANNEL_CONFIDENCE)
    )
    forced_verify = forced_strong | forced_multi

    n = len(validation)
    max_interventions = int(np.floor(TOTAL_INTERVENTION_BUDGET * n))
    review_rows = int(review.sum())
    forced_rows = int(forced_verify.sum())
    score_budget = max(max_interventions - review_rows - forced_rows, 0)

    score_candidates = (~review) & (~forced_verify)
    candidate_scores = linkrisk_scores[score_candidates]

    if score_budget <= 0 or candidate_scores.size == 0:
        verify_threshold = REVIEW_THRESHOLD
    elif score_budget >= candidate_scores.size:
        verify_threshold = 0.0
    else:
        # Select the highest-risk score-band rows without exceeding the budget.
        # np.partition avoids sorting the complete validation score vector.
        kth_index = candidate_scores.size - score_budget
        boundary = float(np.partition(candidate_scores, kth_index)[kth_index])

        # Include all rows strictly above the boundary first. If including all
        # ties at the boundary would exceed budget, move the threshold by one
        # representable float so those tied rows are excluded rather than
        # violating the intervention cap.
        above = int((candidate_scores > boundary).sum())
        at_boundary = int((candidate_scores == boundary).sum())
        if above + at_boundary <= score_budget:
            verify_threshold = boundary
        else:
            verify_threshold = float(np.nextafter(boundary, np.inf))

    verify_by_score = (
        (~review)
        & (~forced_verify)
        & (linkrisk_scores >= verify_threshold)
    )
    verify = forced_verify | verify_by_score
    interventions = review | verify

    print("\n=== Structural Override Floor ===")
    print(f"REVIEW rows:                    {review_rows:,} ({review.mean():.2%})")
    print(f"Strong-evidence forced VERIFY:  {int(forced_strong.sum()):,}")
    print(f"Multi-channel forced VERIFY:    {int(forced_multi.sum()):,}")
    print(f"Forced VERIFY total:            {forced_rows:,} ({forced_verify.mean():.2%})")

    print("\n=== Calibrated Policy ===")
    print(f"VERIFY score threshold:         {verify_threshold:.9f}")
    print(f"Score-band VERIFY rows:         {int(verify_by_score.sum()):,}")
    print(f"Total VERIFY rows:              {int(verify.sum()):,} ({verify.mean():.2%})")
    print(f"Total REVIEW rows:              {review_rows:,} ({review.mean():.2%})")
    print(
        f"Total interventions:            {int(interventions.sum()):,} / {n:,} "
        f"({interventions.mean():.2%})"
    )
    print(f"Budget utilization:             {interventions.sum() / max(max_interventions, 1):.2%}")

    fallback = confidence == 0.0
    fallback_difference = float(
        np.max(np.abs(linkrisk_scores[fallback] - baseline_scores[fallback]))
        if fallback.any()
        else 0.0
    )
    print(f"Exact fallback max difference:  {fallback_difference:.12f}")

    result = {
        "experiment": "linkrisk_verify_budget_calibration_v1",
        "test_evaluated": False,
        "uses_validation_labels_for_threshold": False,
        "total_intervention_budget": TOTAL_INTERVENTION_BUDGET,
        "review_threshold": REVIEW_THRESHOLD,
        "verify_threshold_candidate": verify_threshold,
        "rows": {
            "validation": n,
            "max_interventions": max_interventions,
            "review": review_rows,
            "forced_verify_strong": int(forced_strong.sum()),
            "forced_verify_multi": int(forced_multi.sum()),
            "forced_verify_total": forced_rows,
            "score_band_verify": int(verify_by_score.sum()),
            "verify_total": int(verify.sum()),
            "interventions_total": int(interventions.sum()),
        },
        "shares": {
            "review": float(review.mean()),
            "verify": float(verify.mean()),
            "intervention": float(interventions.mean()),
        },
        "exact_fallback_max_abs_difference": fallback_difference,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RESULTS_DIR / "verify_budget_calibration.json"
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(f"\nSaved {output_path.relative_to(ROOT)}")
    print("This script proposes a policy threshold only; it does not modify the frozen scorer.")
    print("Held-out test remains untouched.\n")


if __name__ == "__main__":
    main()
