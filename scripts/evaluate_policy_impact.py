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

from linkrisk.baseline import (
    TARGET,
    evaluate_scores,
)
from linkrisk.data import chronological_split
from linkrisk.decision import (
    CHAMPION_GATE_STRENGTH,
    CHAMPION_VERSION,
    MULTI_CHANNEL_CONFIDENCE,
    REVIEW_THRESHOLD,
    STRONG_EVIDENCE_CONFIDENCE,
    VERIFY_THRESHOLD,
    RiskAction,
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
ABANDONMENT_SCENARIOS = (0.02, 0.05, 0.10)


def _action_masks(
    scores: np.ndarray,
    confidence: np.ndarray,
    feedback: pd.DataFrame,
) -> tuple[np.ndarray, dict[str, int]]:
    review = scores >= REVIEW_THRESHOLD
    verify_by_score = (~review) & (scores >= VERIFY_THRESHOLD)

    strong_link = feedback["any_strong_confirmed_fraud"].to_numpy(dtype=float) > 0.0
    fraud_channels = feedback["confirmed_fraud_channels"].to_numpy(dtype=float)

    verify_by_strong = (
        (~review)
        & (~verify_by_score)
        & strong_link
        & (confidence >= STRONG_EVIDENCE_CONFIDENCE)
    )
    verify_by_multi = (
        (~review)
        & (~verify_by_score)
        & (~verify_by_strong)
        & (fraud_channels >= 2.0)
        & (confidence >= MULTI_CHANNEL_CONFIDENCE)
    )

    verify = verify_by_score | verify_by_strong | verify_by_multi
    actions = np.full(len(scores), RiskAction.ALLOW.value, dtype=object)
    actions[verify] = RiskAction.VERIFY.value
    actions[review] = RiskAction.REVIEW.value

    reasons = {
        "verify_by_score": int(verify_by_score.sum()),
        "verify_by_strong_evidence_override": int(verify_by_strong.sum()),
        "verify_by_multi_channel_override": int(verify_by_multi.sum()),
    }
    return actions, reasons


def _action_stats(
    action: str,
    mask: np.ndarray,
    y: np.ndarray,
    amounts: np.ndarray,
) -> dict:
    rows = int(mask.sum())
    fraud_mask = mask & (y == 1)
    legit_mask = mask & (y == 0)
    frauds = int(fraud_mask.sum())
    legitimate = int(legit_mask.sum())
    total_frauds = int((y == 1).sum())
    total_legit = int((y == 0).sum())

    return {
        "action": action,
        "rows": rows,
        "row_share": rows / len(y) if len(y) else 0.0,
        "frauds": frauds,
        "fraud_capture_share": frauds / total_frauds if total_frauds else 0.0,
        "legitimate": legitimate,
        "legitimate_share": legitimate / total_legit if total_legit else 0.0,
        "fraud_rate": frauds / rows if rows else 0.0,
        "total_gmv": float(amounts[mask].sum()),
        "fraud_gmv": float(amounts[fraud_mask].sum()),
        "legitimate_gmv": float(amounts[legit_mask].sum()),
    }


def main() -> None:
    print("\n=== LinkRisk Frozen Policy / Business Impact ===\n")
    print(f"Champion:           {CHAMPION_VERSION}")
    print(f"Champion gate:      {CHAMPION_GATE_STRENGTH:.2f}")
    print(f"VERIFY threshold:   {VERIFY_THRESHOLD:.6f}")
    print(f"REVIEW threshold:   {REVIEW_THRESHOLD:.6f}")
    print("No model parameters or thresholds are tuned in this script.")
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
    print("Reconstructing frozen causal relationship + delayed feedback state...")

    relationship = build_relationship_features_v4(development)
    rel_val = relationship.loc[validation.index]

    eligible = pd.Series(False, index=development.index)
    eligible.loc[train.index] = True
    feedback = build_feedback(development, eligible)
    fb_val = feedback.loc[validation.index]

    val_matrix = np.asarray(
        preprocessor.transform(validation[baseline_features]), dtype=np.float32
    )
    y = validation[TARGET].astype(np.int8).to_numpy()
    amounts = (
        pd.to_numeric(validation["TransactionAmt"], errors="coerce")
        .fillna(0.0)
        .to_numpy(dtype=float)
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

    fallback = confidence == 0.0
    fallback_difference = float(
        np.max(np.abs(linkrisk_scores[fallback] - baseline_scores[fallback]))
        if fallback.any()
        else 0.0
    )

    review_pred = (linkrisk_scores >= REVIEW_THRESHOLD).astype(np.int8)
    review_metrics = evaluate_scores(y, linkrisk_scores, REVIEW_THRESHOLD)
    baseline_review_pred = (baseline_scores >= 0.849797).astype(np.int8)

    actions, verify_reasons = _action_masks(linkrisk_scores, confidence, fb_val)
    action_results = []
    for action in (
        RiskAction.ALLOW.value,
        RiskAction.VERIFY.value,
        RiskAction.REVIEW.value,
    ):
        action_results.append(
            _action_stats(action, actions == action, y, amounts)
        )

    print("=== Frozen REVIEW Operating Point ===")
    print(f"Precision: {review_metrics['precision']:.4f}")
    print(f"Recall:    {review_metrics['recall']:.4f}")
    print(f"PR-AUC:    {review_metrics['pr_auc']:.4f}")
    print(f"FPR:       {review_metrics['false_positive_rate']:.4%}")
    print(
        f"TP / FP / TN / FN: {review_metrics['true_positives']} / "
        f"{review_metrics['false_positives']} / {review_metrics['true_negatives']} / "
        f"{review_metrics['false_negatives']}"
    )
    print(f"Exact fallback max difference: {fallback_difference:.12f}\n")

    recovered_fn = int(((y == 1) & (baseline_review_pred == 0) & (review_pred == 1)).sum())
    lost_tp = int(((y == 1) & (baseline_review_pred == 1) & (review_pred == 0)).sum())
    removed_fp = int(((y == 0) & (baseline_review_pred == 1) & (review_pred == 0)).sum())
    new_fp = int(((y == 0) & (baseline_review_pred == 0) & (review_pred == 1)).sum())

    print("=== REVIEW Decision Delta vs Frozen Baseline ===")
    print(f"Recovered baseline FNs: {recovered_fn:,}")
    print(f"Lost baseline TPs:       {lost_tp:,}")
    print(f"Net additional frauds:   {recovered_fn - lost_tp:+,}")
    print(f"Removed baseline FPs:    {removed_fp:,}")
    print(f"New false positives:     {new_fp:,}")
    print(f"Net additional FPs:      {new_fp - removed_fp:+,}\n")

    print("=== Action Distribution ===")
    print(
        f"{'action':8s} {'rows':>9s} {'share':>8s} {'frauds':>8s} "
        f"{'fraud cap':>10s} {'legit':>9s} {'legit share':>11s} {'fraud rate':>11s}"
    )
    print("-" * 86)
    for stats in action_results:
        print(
            f"{stats['action']:8s} {stats['rows']:9,d} {stats['row_share']:8.2%} "
            f"{stats['frauds']:8,d} {stats['fraud_capture_share']:10.2%} "
            f"{stats['legitimate']:9,d} {stats['legitimate_share']:11.2%} "
            f"{stats['fraud_rate']:11.2%}"
        )

    verify_stats = next(x for x in action_results if x["action"] == RiskAction.VERIFY.value)
    review_stats = next(x for x in action_results if x["action"] == RiskAction.REVIEW.value)
    allow_stats = next(x for x in action_results if x["action"] == RiskAction.ALLOW.value)

    print("\n=== VERIFY Routing Reasons ===")
    print(f"Score-band VERIFY:                  {verify_reasons['verify_by_score']:,}")
    print(
        "Strong-evidence VERIFY override:    "
        f"{verify_reasons['verify_by_strong_evidence_override']:,}"
    )
    print(
        "Multi-channel VERIFY override:      "
        f"{verify_reasons['verify_by_multi_channel_override']:,}"
    )

    intervention_mask = actions != RiskAction.ALLOW.value
    intervention_frauds = int(((y == 1) & intervention_mask).sum())
    intervention_legit = int(((y == 0) & intervention_mask).sum())
    total_frauds = int((y == 1).sum())
    total_legit = int((y == 0).sum())

    print("\n=== Intervention Coverage ===")
    print(
        f"Frauds routed to VERIFY/REVIEW: {intervention_frauds:,} / {total_frauds:,} "
        f"({intervention_frauds / total_frauds:.2%})"
    )
    print(
        f"Legitimate routed to friction:  {intervention_legit:,} / {total_legit:,} "
        f"({intervention_legit / total_legit:.2%})"
    )
    print(
        f"Frauds left in ALLOW:            {allow_stats['frauds']:,} / {total_frauds:,} "
        f"({allow_stats['fraud_capture_share']:.2%})"
    )

    print("\n=== Legitimate GMV Exposure ===")
    print(f"VERIFY legitimate GMV: {verify_stats['legitimate_gmv']:,.2f}")
    print(f"REVIEW legitimate GMV: {review_stats['legitimate_gmv']:,.2f}")
    print(
        "These are dataset TransactionAmt units; no currency is asserted because "
        "IEEE-CIS does not provide a business currency for this analysis."
    )

    abandonment = []
    print("\n=== VERIFY Abandonment Sensitivity ===")
    print(
        "Assumption: only legitimate VERIFY traffic is exposed to verification abandonment."
    )
    print(f"{'abandonment':>12s} {'expected legit GMV lost':>26s}")
    print("-" * 40)
    for rate in ABANDONMENT_SCENARIOS:
        expected_lost = verify_stats["legitimate_gmv"] * rate
        abandonment.append(
            {
                "abandonment_rate": rate,
                "expected_legitimate_gmv_lost": expected_lost,
            }
        )
        print(f"{rate:12.0%} {expected_lost:26,.2f}")

    result = {
        "experiment": "linkrisk_policy_impact_validation_v1",
        "champion_version": CHAMPION_VERSION,
        "test_evaluated": False,
        "policy": {
            "champion_gate_strength": CHAMPION_GATE_STRENGTH,
            "verify_threshold": VERIFY_THRESHOLD,
            "review_threshold": REVIEW_THRESHOLD,
            "strong_evidence_confidence": STRONG_EVIDENCE_CONFIDENCE,
            "multi_channel_confidence": MULTI_CHANNEL_CONFIDENCE,
        },
        "review_metrics": review_metrics,
        "exact_fallback_max_abs_difference": fallback_difference,
        "review_delta_vs_baseline": {
            "recovered_baseline_false_negatives": recovered_fn,
            "lost_baseline_true_positives": lost_tp,
            "net_additional_frauds": recovered_fn - lost_tp,
            "removed_baseline_false_positives": removed_fp,
            "new_false_positives": new_fp,
            "net_additional_false_positives": new_fp - removed_fp,
        },
        "actions": action_results,
        "verify_routing_reasons": verify_reasons,
        "intervention": {
            "frauds": intervention_frauds,
            "fraud_share": intervention_frauds / total_frauds if total_frauds else 0.0,
            "legitimate": intervention_legit,
            "legitimate_share": intervention_legit / total_legit if total_legit else 0.0,
        },
        "verification_abandonment_sensitivity": abandonment,
        "amount_unit_note": "TransactionAmt dataset units; no currency asserted.",
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RESULTS_DIR / "policy_impact_validation.json"
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(f"\nSaved {output_path.relative_to(ROOT)}")
    print("Held-out test remains untouched.\n")


if __name__ == "__main__":
    main()
