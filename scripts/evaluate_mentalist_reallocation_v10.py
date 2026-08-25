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
from linkrisk.engine import FrozenChampionScorer
from linkrisk.feedback_features_v5 import build_feedback_features_v5
from linkrisk.mentalist_features_v7 import MENTALIST_FEATURES, build_mentalist_features_v7, clue_activations
from linkrisk.mentalist_router_v10 import reallocate_verify_capacity
from linkrisk.mentalist_router_v9 import select_top_by_score
from linkrisk.relationship_features_v4 import build_relationship_features_v4

DATA_DIR = ROOT / "data" / "raw"
MODEL_DIR = ROOT / "artifacts" / "models"
RESULTS_DIR = ROOT / "artifacts" / "results"

MIN_CLUE_FAMILIES = 2
JANE_RESERVATION = 0.0100
MIN_CAPTURE_LIFT = 0.005
MAX_FRICTION_DELTA = 0.0
MIN_NOVEL_JANE_FRAUDS = 15


def load_data() -> pd.DataFrame:
    tx_path = DATA_DIR / "train_transaction.csv"
    id_path = DATA_DIR / "train_identity.csv"
    required_tx = {ID_COL, TIME_COL, TARGET, *BASE_RAW_FEATURES}
    required_id = {ID_COL, *BASE_RAW_FEATURES}
    tx = pd.read_csv(tx_path, usecols=lambda c: c in required_tx, low_memory=False)
    identity = pd.read_csv(id_path, usecols=lambda c: c in required_id, low_memory=False)
    return merge_transaction_identity(tx, identity)


def policy_metrics(actions: np.ndarray, y: np.ndarray) -> dict:
    intervention = actions != "ALLOW"
    verify = actions == "VERIFY"
    review = actions == "REVIEW"
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
        }

    return {
        "ALLOW": bucket(actions == "ALLOW"),
        "VERIFY": bucket(verify),
        "REVIEW": bucket(review),
        "intervention": bucket(intervention),
        "fraud_capture": int(((y == 1) & intervention).sum()) / total_fraud,
        "legitimate_friction": int(((y == 0) & intervention).sum()) / total_legit,
    }


def subset_stats(mask: np.ndarray, y: np.ndarray, risk: np.ndarray) -> dict:
    rows = int(mask.sum())
    frauds = int(((y == 1) & mask).sum())
    legit = int(((y == 0) & mask).sum())
    return {
        "rows": rows,
        "frauds": frauds,
        "legitimate": legit,
        "fraud_rate": frauds / rows if rows else 0.0,
        "mean_v5_risk": float(np.mean(risk[mask])) if rows else 0.0,
        "min_v5_risk": float(np.min(risk[mask])) if rows else None,
        "max_v5_risk": float(np.max(risk[mask])) if rows else None,
    }


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
    del proactive, relationship, feedback, development

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
    jane_selected, derived_cutoff = select_top_by_score(
        jane_scores,
        jane_eligible,
        jane_target_rows,
    )
    v8_primary = next(
        row for row in v8["verify_budgets"]
        if abs(float(row["budget"]) - JANE_RESERVATION) < 1e-12
    )
    stored_cutoff = float(v8_primary["jane_score_threshold"])

    v5 = champion.score_batch(
        validation,
        val_relationship,
        val_feedback,
    )
    v5_actions = v5["action"].astype(str).to_numpy()
    v5_risk = v5["linkrisk_risk"].to_numpy(dtype=float)

    routed = reallocate_verify_capacity(
        v5_actions=v5_actions,
        v5_risk=v5_risk,
        jane_selected=jane_selected,
    )

    y = validation[TARGET].astype(np.int8).to_numpy()
    stable = policy_metrics(v5_actions, y)
    final = policy_metrics(routed.actions, y)
    added = subset_stats(routed.added_jane, y, v5_risk)
    evicted = subset_stats(routed.evicted_v5_verify, y, v5_risk)

    capture_lift = final["fraud_capture"] - stable["fraud_capture"]
    friction_delta = final["legitimate_friction"] - stable["legitimate_friction"]
    same_capacity = final["intervention"]["rows"] == stable["intervention"]["rows"]
    review_unchanged = bool(np.array_equal(
        routed.actions[v5_actions == "REVIEW"],
        v5_actions[v5_actions == "REVIEW"],
    ))
    useful = bool(
        same_capacity
        and review_unchanged
        and added["frauds"] >= MIN_NOVEL_JANE_FRAUDS
        and capture_lift >= MIN_CAPTURE_LIFT
        and friction_delta <= MAX_FRICTION_DELTA + 1e-12
    )

    payload = {
        "experiment": "mentalist_v1.0_one_for_one_reallocation",
        "development_note": (
            "Architecture was motivated by the failed v0.9 validation router: "
            "historical-prior overrides should not automatically outrank stronger current evidence."
        ),
        "held_out_test": {"status": "sealed", "rows": sealed_rows, "labels_used": False},
        "jane": {
            "reservation": JANE_RESERVATION,
            "min_clue_families": MIN_CLUE_FAMILIES,
            "selected_rows": int(jane_selected.sum()),
            "derived_cutoff": derived_cutoff,
            "v8_stored_cutoff": stored_cutoff,
        },
        "stable_v5": stable,
        "reallocated_policy": final,
        "added_mentalist_cases": added,
        "evicted_v5_verify_cases": evicted,
        "promotion": {
            "same_intervention_capacity": same_capacity,
            "review_unchanged": review_unchanged,
            "min_novel_jane_frauds": MIN_NOVEL_JANE_FRAUDS,
            "min_capture_lift": MIN_CAPTURE_LIFT,
            "max_friction_delta": MAX_FRICTION_DELTA,
            "capture_lift": float(capture_lift),
            "friction_delta": float(friction_delta),
            "pass": useful,
        },
    }

    out = RESULTS_DIR / "mentalist_v10_reallocation_validation.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("\n=== Mentalist v1.0 — One-for-One Case Reallocation ===")
    print("The frozen v0.5 policy is the starting point; REVIEW is immutable.")
    print("Jane may add only cases v0.5 would ALLOW, replacing the same number of lowest-risk v0.5 VERIFY cases.")
    print("Routing uses no validation labels. Held-out test remains sealed.\n")

    print("Stable v0.5")
    print(f"  intervention: {100*stable['intervention']['row_share']:.2f}%")
    print(f"  fraud capture:{100*stable['fraud_capture']:.2f}%")
    print(f"  legit friction:{100*stable['legitimate_friction']:.2f}%")

    print("\nMentalist substitutions")
    print(f"  Jane selected total:       {int(jane_selected.sum()):,}")
    print(f"  novel Jane cases added:    {added['rows']:,}")
    print(f"  frauds in added Jane:      {added['frauds']:,}")
    print(f"  added Jane fraud rate:     {100*added['fraud_rate']:.2f}%")
    print(f"  v0.5 VERIFY cases evicted: {evicted['rows']:,}")
    print(f"  frauds in evicted cases:   {evicted['frauds']:,}")
    print(f"  evicted fraud rate:        {100*evicted['fraud_rate']:.2f}%")
    print(f"  max evicted v0.5 risk:     {evicted['max_v5_risk'] if evicted['max_v5_risk'] is not None else 0:.6f}")

    print("\nReallocated policy")
    print(f"  intervention: {100*final['intervention']['row_share']:.2f}%")
    print(f"  fraud capture:{100*final['fraud_capture']:.2f}%")
    print(f"  legit friction:{100*final['legitimate_friction']:.2f}%")
    print(f"  capture lift: {100*capture_lift:+.2f} pp")
    print(f"  friction delta:{100*friction_delta:+.2f} pp")

    print("\nPromotion gate")
    print(f"  same capacity:              {'YES' if same_capacity else 'NO'}")
    print(f"  REVIEW unchanged:           {'YES' if review_unchanged else 'NO'}")
    print(f"  capture lift required:      >= +{100*MIN_CAPTURE_LIFT:.2f} pp")
    print("  legitimate friction:        must not increase")
    print(f"  Candidate status:           {'PASS' if useful else 'FAIL'}")
    print(f"\nSaved {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
