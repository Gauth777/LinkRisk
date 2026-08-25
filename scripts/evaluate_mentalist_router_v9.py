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
from linkrisk.decision import MULTI_CHANNEL_CONFIDENCE, STRONG_EVIDENCE_CONFIDENCE, VERIFY_THRESHOLD
from linkrisk.engine import FrozenChampionScorer
from linkrisk.feedback_features_v5 import build_feedback_features_v5
from linkrisk.mentalist_features_v7 import MENTALIST_FEATURES, build_mentalist_features_v7, clue_activations
from linkrisk.mentalist_router_v9 import route_under_capacity, select_top_by_score
from linkrisk.relationship_features_v4 import build_relationship_features_v4

DATA_DIR = ROOT / "data" / "raw"
MODEL_DIR = ROOT / "artifacts" / "models"
RESULTS_DIR = ROOT / "artifacts" / "results"

MIN_CLUE_FAMILIES = 2
JANE_RESERVATION = 0.0100
TOTAL_INTERVENTION_BUDGET = 0.0600
MIN_UNIQUE_JANE_FRAUDS = 15
MIN_CAPTURE_LIFT = 0.005
MAX_FRICTION_DELTA = 0.0


def load_data() -> pd.DataFrame:
    tx_path = DATA_DIR / "train_transaction.csv"
    id_path = DATA_DIR / "train_identity.csv"
    required_tx = {ID_COL, TIME_COL, TARGET, *BASE_RAW_FEATURES}
    required_id = {ID_COL, *BASE_RAW_FEATURES}
    tx = pd.read_csv(tx_path, usecols=lambda c: c in required_tx, low_memory=False)
    identity = pd.read_csv(id_path, usecols=lambda c: c in required_id, low_memory=False)
    return merge_transaction_identity(tx, identity)


def policy_metrics(actions: np.ndarray, y: np.ndarray) -> dict:
    review = actions == "REVIEW"
    verify = actions == "VERIFY"
    intervention = review | verify
    total_fraud = int((y == 1).sum())
    total_legit = int((y == 0).sum())

    def bucket(mask: np.ndarray) -> dict:
        rows = int(mask.sum())
        frauds = int(((y == 1) & mask).sum())
        legit = int(((y == 0) & mask).sum())
        return {
            "rows": rows,
            "row_share": rows / len(y),
            "frauds": frauds,
            "legitimate": legit,
            "fraud_rate": frauds / rows if rows else 0.0,
            "fraud_capture": frauds / total_fraud if total_fraud else 0.0,
            "legitimate_share": legit / total_legit if total_legit else 0.0,
        }

    return {
        "ALLOW": bucket(actions == "ALLOW"),
        "VERIFY": bucket(verify),
        "REVIEW": bucket(review),
        "intervention": bucket(intervention),
        "fraud_capture": int(((y == 1) & intervention).sum()) / total_fraud,
        "legitimate_friction": int(((y == 0) & intervention).sum()) / total_legit,
    }


def route_reason_stats(reasons: np.ndarray, y: np.ndarray) -> list[dict]:
    rows = []
    for reason in (
        "V5_REVIEW",
        "TRUSTED_FRAUD_OVERRIDE",
        "MENTALIST_PROACTIVE",
        "V5_SCORE_VERIFY",
    ):
        mask = reasons == reason
        count = int(mask.sum())
        frauds = int(((y == 1) & mask).sum())
        legitimate = int(((y == 0) & mask).sum())
        rows.append(
            {
                "reason": reason,
                "rows": count,
                "frauds": frauds,
                "legitimate": legitimate,
                "fraud_rate": frauds / count if count else 0.0,
            }
        )
    return rows


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading IEEE-CIS development data...")
    data = load_data()
    train, validation, sealed_test = chronological_split(data)
    sealed_rows = len(sealed_test)
    del sealed_test
    del data

    with (RESULTS_DIR / "mentalist_v7_validation.json").open("r", encoding="utf-8") as f:
        v7 = json.load(f)
    with (RESULTS_DIR / "mentalist_v8_investigator_validation.json").open("r", encoding="utf-8") as f:
        v8 = json.load(f)
    with (RESULTS_DIR / "baseline_features.json").open("r", encoding="utf-8") as f:
        baseline_features = json.load(f)
    with (RESULTS_DIR / "baseline_validation.json").open("r", encoding="utf-8") as f:
        baseline_snapshot = json.load(f)

    mentalist = joblib.load(MODEL_DIR / "mentalist_v7_candidate.joblib")
    baseline_preprocessor = joblib.load(MODEL_DIR / "baseline_preprocessor.joblib")
    baseline_model = joblib.load(MODEL_DIR / "baseline_xgboost.joblib")
    champion = FrozenChampionScorer.from_artifacts(ROOT)

    print("Building proactive and trusted-memory state across train -> validation...")
    development = pd.concat([train, validation], axis=0)
    proactive = build_mentalist_features_v7(development)
    relationship = build_relationship_features_v4(development)

    label_eligible = pd.Series(False, index=development.index, dtype=bool)
    label_eligible.loc[train.index] = True
    feedback = build_feedback_features_v5(development, label_eligible)

    val_proactive = proactive.loc[validation.index]
    val_relationship = relationship.loc[validation.index]
    val_feedback = feedback.loc[validation.index]
    del proactive
    del relationship
    del feedback
    del development

    val_raw = baseline_preprocessor.transform(validation[baseline_features])
    baseline_scores = baseline_model.predict_proba(val_raw)[:, 1]
    baseline_threshold = float(baseline_snapshot["metrics"]["threshold"])
    baseline_review = baseline_scores >= baseline_threshold

    clues = clue_activations(val_proactive, v7["clue_thresholds"])
    clue_count = clues["independent_clue_count"].to_numpy(dtype=int)

    x_val = val_proactive[MENTALIST_FEATURES].copy()
    x_val.insert(0, "baseline_oof_risk", baseline_scores)
    x_val = x_val.replace([np.inf, -np.inf], np.nan).fillna(0.0).astype(np.float32)
    jane_scores = mentalist.predict_proba(x_val)[:, 1]

    jane_eligible = (~baseline_review) & (clue_count >= MIN_CLUE_FAMILIES)
    jane_target_rows = int(round(len(validation) * JANE_RESERVATION))
    jane_v8_selected, jane_cutoff = select_top_by_score(
        jane_scores,
        jane_eligible,
        jane_target_rows,
    )

    v8_primary = next(
        row for row in v8["verify_budgets"]
        if abs(float(row["budget"]) - JANE_RESERVATION) < 1e-12
    )
    stored_jane_cutoff = float(v8_primary["jane_score_threshold"])

    v5 = champion.score_batch(
        validation,
        val_relationship,
        val_feedback,
    )
    v5_actions = v5["action"].astype(str).to_numpy()
    v5_risk = v5["linkrisk_risk"].to_numpy(dtype=float)
    v5_review = v5_actions == "REVIEW"
    v5_verify = v5_actions == "VERIFY"

    confidence = val_feedback["feedback_confidence"].to_numpy(dtype=float)
    strong = val_feedback["any_strong_confirmed_fraud"].to_numpy(dtype=float) > 0.0
    channels = val_feedback["confirmed_fraud_channels"].to_numpy(dtype=float)
    forced_rule = (
        (strong & (confidence >= STRONG_EVIDENCE_CONFIDENCE))
        | ((channels >= 2.0) & (confidence >= MULTI_CHANNEL_CONFIDENCE))
    )
    v5_forced_verify = v5_verify & (v5_risk < VERIFY_THRESHOLD) & forced_rule
    v5_score_verify = v5_verify & (~v5_forced_verify)

    y = validation[TARGET].astype(np.int8).to_numpy()
    v5_intervention = v5_review | v5_verify

    jane_overlap = {
        "selected_rows": int(jane_v8_selected.sum()),
        "selected_frauds": int(((y == 1) & jane_v8_selected).sum()),
        "overlap_v5_review_rows": int((jane_v8_selected & v5_review).sum()),
        "overlap_v5_forced_verify_rows": int((jane_v8_selected & v5_forced_verify).sum()),
        "overlap_v5_score_verify_rows": int((jane_v8_selected & v5_score_verify).sum()),
        "unique_beyond_v5_rows": int((jane_v8_selected & (~v5_intervention)).sum()),
        "unique_beyond_v5_frauds": int(((y == 1) & jane_v8_selected & (~v5_intervention)).sum()),
        "unique_beyond_v5_legitimate": int(((y == 0) & jane_v8_selected & (~v5_intervention)).sum()),
    }

    total_budget_rows = int(np.floor(len(validation) * TOTAL_INTERVENTION_BUDGET))
    routed = route_under_capacity(
        v5_review=v5_review,
        v5_forced_verify=v5_forced_verify,
        jane_candidates=jane_v8_selected,
        jane_scores=jane_scores,
        v5_score_verify=v5_score_verify,
        v5_risk=v5_risk,
        total_budget_rows=total_budget_rows,
    )

    stable_metrics = policy_metrics(v5_actions, y)
    routed_metrics = policy_metrics(routed.actions, y)
    reasons = route_reason_stats(routed.reasons, y)

    capture_lift = routed_metrics["fraud_capture"] - stable_metrics["fraud_capture"]
    friction_delta = routed_metrics["legitimate_friction"] - stable_metrics["legitimate_friction"]
    budget_ok = routed_metrics["intervention"]["row_share"] <= TOTAL_INTERVENTION_BUDGET + 1e-12
    complementarity_ok = jane_overlap["unique_beyond_v5_frauds"] >= MIN_UNIQUE_JANE_FRAUDS
    policy_ok = capture_lift >= MIN_CAPTURE_LIFT and friction_delta <= MAX_FRICTION_DELTA + 1e-12
    useful = bool(budget_ok and complementarity_ok and policy_ok)

    payload = {
        "experiment": "mentalist_v0.9_capacity_router",
        "held_out_test": {"status": "sealed", "rows": sealed_rows, "labels_used": False},
        "jane": {
            "reservation": JANE_RESERVATION,
            "min_clue_families": MIN_CLUE_FAMILIES,
            "selected_rows": int(jane_v8_selected.sum()),
            "derived_cutoff": jane_cutoff,
            "v8_stored_cutoff": stored_jane_cutoff,
        },
        "routing": {
            "total_intervention_budget": TOTAL_INTERVENTION_BUDGET,
            "total_budget_rows": total_budget_rows,
            "priority": [
                "V5_REVIEW",
                "TRUSTED_FRAUD_OVERRIDE",
                "MENTALIST_PROACTIVE",
                "V5_SCORE_VERIFY",
            ],
            "validation_jane_cutoff": routed.jane_cutoff,
            "validation_v5_score_fill_cutoff": routed.v5_score_cutoff,
        },
        "jane_complementarity": jane_overlap,
        "stable_v5_policy": stable_metrics,
        "mentalist_router_policy": routed_metrics,
        "route_reason_stats": reasons,
        "promotion": {
            "min_unique_jane_frauds_beyond_v5": MIN_UNIQUE_JANE_FRAUDS,
            "min_fraud_capture_lift": MIN_CAPTURE_LIFT,
            "max_legitimate_friction_delta": MAX_FRICTION_DELTA,
            "unique_jane_frauds": jane_overlap["unique_beyond_v5_frauds"],
            "fraud_capture_lift": float(capture_lift),
            "legitimate_friction_delta": float(friction_delta),
            "budget_ok": bool(budget_ok),
            "pass": useful,
        },
    }

    out = RESULTS_DIR / "mentalist_v9_router_validation.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("\n=== Mentalist v0.9 — Capacity-Preserving Case Router ===")
    print("Hard REVIEW remains v0.5. Trusted memory and proactive Jane are separate evidence channels.")
    print("Held-out test remains sealed.\n")

    print("Jane v0.8 complementarity")
    print(f"  selected rows:              {jane_overlap['selected_rows']:,}")
    print(f"  selected frauds:            {jane_overlap['selected_frauds']:,}")
    print(f"  overlap v0.5 REVIEW:        {jane_overlap['overlap_v5_review_rows']:,}")
    print(f"  overlap trusted VERIFY:     {jane_overlap['overlap_v5_forced_verify_rows']:,}")
    print(f"  overlap score VERIFY:       {jane_overlap['overlap_v5_score_verify_rows']:,}")
    print(f"  unique beyond v0.5:         {jane_overlap['unique_beyond_v5_rows']:,}")
    print(f"  unique frauds beyond v0.5:  {jane_overlap['unique_beyond_v5_frauds']:,}")

    print("\nStable v0.5 full policy")
    print(f"  intervention: {100*stable_metrics['intervention']['row_share']:.2f}%")
    print(f"  fraud capture:{100*stable_metrics['fraud_capture']:.2f}%")
    print(f"  legit friction:{100*stable_metrics['legitimate_friction']:.2f}%")
    print(f"  VERIFY fraud rate:{100*stable_metrics['VERIFY']['fraud_rate']:.2f}%")

    print("\nMentalist router at <=6% total intervention")
    print(f"  intervention: {100*routed_metrics['intervention']['row_share']:.2f}%")
    print(f"  fraud capture:{100*routed_metrics['fraud_capture']:.2f}%")
    print(f"  legit friction:{100*routed_metrics['legitimate_friction']:.2f}%")
    print(f"  VERIFY fraud rate:{100*routed_metrics['VERIFY']['fraud_rate']:.2f}%")
    print(f"  capture lift: {100*capture_lift:+.2f} pp")
    print(f"  friction delta:{100*friction_delta:+.2f} pp")

    print("\nRouting contributions")
    for row in reasons:
        print(
            f"  {row['reason']:<24} rows={row['rows']:>5,} "
            f"frauds={row['frauds']:>4,} fraud_rate={100*row['fraud_rate']:>6.2f}%"
        )

    print("\nPromotion gate")
    print(f"  unique Jane frauds required: >= {MIN_UNIQUE_JANE_FRAUDS}")
    print(f"  capture lift required:       >= +{100*MIN_CAPTURE_LIFT:.2f} pp")
    print("  legitimate friction:         must not increase")
    print(f"  Candidate status:            {'PASS' if useful else 'FAIL'}")
    print(f"\nSaved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
