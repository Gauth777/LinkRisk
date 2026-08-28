from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from linkrisk.baseline import (
    BASE_RAW_FEATURES,
    ID_COL,
    TARGET,
    TIME_COL,
    evaluate_scores,
    merge_transaction_identity,
)
from linkrisk.data import chronological_split
from linkrisk.engine import FrozenChampionScorer
from linkrisk.feedback_features_v5 import build_feedback_features_v5
from linkrisk.mentalist_features_v7 import build_mentalist_features_v7
from linkrisk.mentalist_runtime_policy import (
    FrozenMentalistScorer,
    apply_runtime_policy,
)
from linkrisk.relationship_features_v4 import build_relationship_features_v4

DATA_DIR = ROOT / "data" / "raw"
RESULTS_DIR = ROOT / "artifacts" / "results"
FINAL_RESULT = RESULTS_DIR / "final_heldout_test.json"

REQUIRED_FILES = (
    DATA_DIR / "train_transaction.csv",
    DATA_DIR / "train_identity.csv",
    ROOT / "artifacts" / "models" / "baseline_preprocessor.joblib",
    ROOT / "artifacts" / "models" / "baseline_xgboost.joblib",
    ROOT / "artifacts" / "models" / "feedback_specialist_v5.joblib",
    ROOT / "artifacts" / "models" / "mentalist_v7_candidate.joblib",
    RESULTS_DIR / "baseline_features.json",
    RESULTS_DIR / "baseline_validation.json",
    RESULTS_DIR / "mentalist_v7_validation.json",
    RESULTS_DIR / "mentalist_runtime_policy.json",
)

FP_COST_SCENARIOS_INR = (5, 10, 25, 50)


def _git_head() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


def _load_data() -> pd.DataFrame:
    tx_path = DATA_DIR / "train_transaction.csv"
    id_path = DATA_DIR / "train_identity.csv"
    required_tx = {ID_COL, TIME_COL, TARGET, *BASE_RAW_FEATURES}
    required_id = {ID_COL, *BASE_RAW_FEATURES}
    tx = pd.read_csv(
        tx_path,
        usecols=lambda column: column in required_tx,
        low_memory=False,
    )
    identity = pd.read_csv(
        id_path,
        usecols=lambda column: column in required_id,
        low_memory=False,
    )
    return merge_transaction_identity(tx, identity)


def _action_metrics(actions: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    actions = np.asarray(actions, dtype=object)
    y = np.asarray(y, dtype=np.int8)
    intervention = actions != "ALLOW"
    verify = actions == "VERIFY"
    review = actions == "REVIEW"

    total_fraud = int((y == 1).sum())
    total_legitimate = int((y == 0).sum())
    tp = int(((y == 1) & intervention).sum())
    fp = int(((y == 0) & intervention).sum())
    fn = total_fraud - tp
    tn = total_legitimate - fp

    def bucket(mask: np.ndarray) -> dict[str, Any]:
        rows = int(mask.sum())
        frauds = int(((y == 1) & mask).sum())
        legitimate = int(((y == 0) & mask).sum())
        return {
            "rows": rows,
            "row_share": rows / len(y) if len(y) else 0.0,
            "frauds": frauds,
            "legitimate": legitimate,
            "fraud_rate": frauds / rows if rows else 0.0,
        }

    return {
        "precision": tp / (tp + fp) if (tp + fp) else 0.0,
        "recall": tp / total_fraud if total_fraud else 0.0,
        "false_positive_rate": fp / total_legitimate if total_legitimate else 0.0,
        "intervention_rate": int(intervention.sum()) / len(y) if len(y) else 0.0,
        "true_positives": tp,
        "false_positives": fp,
        "true_negatives": tn,
        "false_negatives": fn,
        "ALLOW": bucket(actions == "ALLOW"),
        "VERIFY": bucket(verify),
        "REVIEW": bucket(review),
        "intervention": bucket(intervention),
    }


def _transition_stats(
    v5_actions: np.ndarray,
    final_actions: np.ndarray,
    y: np.ndarray,
    promoted: np.ndarray,
    displaced: np.ndarray,
) -> dict[str, Any]:
    return {
        "promoted_by_mentalist": {
            "rows": int(promoted.sum()),
            "frauds": int(((y == 1) & promoted).sum()),
            "legitimate": int(((y == 0) & promoted).sum()),
        },
        "displaced_v5_verify": {
            "rows": int(displaced.sum()),
            "frauds": int(((y == 1) & displaced).sum()),
            "legitimate": int(((y == 0) & displaced).sum()),
        },
        "v5_review_unchanged": bool(
            np.array_equal(
                final_actions[np.asarray(v5_actions, dtype=object) == "REVIEW"],
                np.asarray(v5_actions, dtype=object)[
                    np.asarray(v5_actions, dtype=object) == "REVIEW"
                ],
            )
        ),
        "intervention_delta_rows": int(
            (np.asarray(final_actions, dtype=object) != "ALLOW").sum()
            - (np.asarray(v5_actions, dtype=object) != "ALLOW").sum()
        ),
    }


def _label_digest(ids: np.ndarray, y: np.ndarray) -> str:
    digest = hashlib.sha256()
    for tx_id, label in zip(ids, y):
        digest.update(f"{tx_id}:{int(label)}\n".encode("utf-8"))
    return digest.hexdigest()


def preflight() -> int:
    print("=== LinkRisk final held-out evaluation preflight ===\n")
    missing = [path for path in REQUIRED_FILES if not path.exists()]
    for path in REQUIRED_FILES:
        status = "OK" if path.exists() else "MISSING"
        print(f"[{status:7s}] {path.relative_to(ROOT)}")

    if FINAL_RESULT.exists():
        print(f"\n[LOCKED ] {FINAL_RESULT.relative_to(ROOT)} already exists")
        print("The one-shot held-out result has already been materialized; do not rerun it.")
        return 3

    if missing:
        print("\nPreflight FAILED: required local files are missing.")
        return 2

    champion = FrozenChampionScorer.from_artifacts(ROOT)
    mentalist = FrozenMentalistScorer.from_artifacts(ROOT)
    policy = mentalist.policy

    print("\nFrozen runtime policy")
    print(f"  version                         : {policy.version}")
    print(f"  minimum clue families           : {policy.min_clue_families}")
    print(f"  Jane score threshold            : {policy.jane_score_threshold:.15f}")
    print(f"  baseline REVIEW threshold       : {policy.baseline_review_threshold:.15f}")
    print(f"  v0.5 VERIFY displacement        : {policy.v5_verify_displacement_threshold:.15f}")
    print(f"  validation intervention target  : {policy.validation_intervention_target:.2%}")
    print(f"  champion baseline features      : {len(champion.baseline_features)}")
    print("\nHeld-out labels have NOT been evaluated by this preflight.")
    print("Preflight PASSED.")
    return 0


def execute_final() -> int:
    if FINAL_RESULT.exists():
        print(f"REFUSING TO RUN: {FINAL_RESULT.relative_to(ROOT)} already exists.")
        print("This evaluator is intentionally one-shot. Do not delete/overwrite the result to tune on test.")
        return 3

    missing = [path for path in REQUIRED_FILES if not path.exists()]
    if missing:
        print("Missing required files:")
        for path in missing:
            print(f"  - {path.relative_to(ROOT)}")
        return 2

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print("=== LinkRisk FINAL SEALED HELD-OUT EVALUATION ===")
    print("No threshold selection or model fitting occurs in this script.")
    print("Test outcomes are excluded from all relationship/trusted-memory predictions.\n")

    champion = FrozenChampionScorer.from_artifacts(ROOT)
    mentalist = FrozenMentalistScorer.from_artifacts(ROOT)
    policy = mentalist.policy

    print("Loading IEEE-CIS data and reconstructing the frozen chronological split...")
    merged = _load_data()
    train, validation, test = chronological_split(merged)
    del merged

    # Extract the sealed outcomes once, then remove them from the frame used to
    # construct every feature and prediction. They are referenced again only
    # after all frozen predictions/actions have been produced.
    test_ids = test[ID_COL].to_numpy(copy=True)
    y_test = test[TARGET].astype(np.int8).to_numpy(copy=True)
    test_index = test.index.copy()
    test_rows = len(test)
    test_unlabeled = test.copy()
    test_unlabeled[TARGET] = 0
    del test

    if len(train) == 0 or len(validation) == 0 or test_rows == 0:
        raise RuntimeError("Chronological split produced an empty partition")
    if float(train[TIME_COL].max()) > float(validation[TIME_COL].min()):
        raise RuntimeError("Train/validation chronology is not monotonic")
    if float(validation[TIME_COL].max()) > float(test_unlabeled[TIME_COL].min()):
        raise RuntimeError("Validation/test chronology is not monotonic")

    print(f"  train rows      : {len(train):,}")
    print(f"  validation rows : {len(validation):,}")
    print(f"  held-out rows   : {test_rows:,}")

    development = pd.concat([train, validation], axis=0).sort_values(
        TIME_COL, kind="mergesort"
    )
    state = pd.concat([development, test_unlabeled], axis=0).sort_values(
        TIME_COL, kind="mergesort"
    )

    # Trusted feedback for test may use train+validation outcomes, but never a
    # test outcome. The feature builder itself applies the fixed 72-hour delay.
    label_eligible = pd.Series(False, index=state.index, dtype=bool)
    label_eligible.loc[development.index] = True
    if bool(label_eligible.loc[test_index].any()):
        raise AssertionError("Held-out labels were accidentally marked feedback-eligible")

    print("Building causal relationship, delayed-feedback and Mentalist state...")
    relationship = build_relationship_features_v4(state)
    feedback = build_feedback_features_v5(state, label_eligible)
    proactive = build_mentalist_features_v7(state)

    test_relationship = relationship.loc[test_index]
    test_feedback = feedback.loc[test_index]
    test_proactive = proactive.loc[test_index]
    del relationship, feedback, proactive, state, development

    print("Scoring frozen baseline + v0.5 champion...")
    raw_matrix = champion.preprocessor.transform(
        test_unlabeled[champion.baseline_features]
    )
    baseline_scores = champion.baseline_model.predict_proba(raw_matrix)[:, 1]

    v5 = champion.score_batch(
        test_unlabeled,
        test_relationship,
        test_feedback,
    )
    v5_actions = v5["action"].astype(str).to_numpy()
    v5_risk = v5["linkrisk_risk"].to_numpy(dtype=float)

    print("Applying frozen Mentalist v1.0 runtime routing...")
    mentalist_state = mentalist.score_batch(test_proactive, baseline_scores)
    routed = apply_runtime_policy(
        v5_actions=v5_actions,
        v5_risk=v5_risk,
        baseline_risk=baseline_scores,
        mentalist_state=mentalist_state,
        policy=policy,
    )
    final_actions = routed.actions.astype(str)

    # Predictions are now frozen. Only from this point onward are held-out
    # outcomes used, strictly for aggregate evaluation.
    print("Predictions frozen. Evaluating once against held-out outcomes...\n")

    baseline_detector = evaluate_scores(
        y_test,
        baseline_scores,
        policy.baseline_review_threshold,
    )
    v5_review_detector = evaluate_scores(
        y_test,
        v5_risk,
        # v0.5 REVIEW is exactly the REVIEW action boundary embodied by the
        # frozen champion. Derive it from actual frozen REVIEW scores without
        # choosing anything from test labels.
        float(min(v5_risk[v5_actions == "REVIEW"]))
        if bool((v5_actions == "REVIEW").any())
        else 1.0,
    )
    # The threshold field above is descriptive only. For exact hard-review
    # confusion counts, overwrite prediction metrics from the frozen actions.
    v5_review_actions = np.where(v5_actions == "REVIEW", "REVIEW", "ALLOW")
    v5_review_operational = _action_metrics(v5_review_actions, y_test)
    for key in (
        "precision",
        "recall",
        "false_positive_rate",
        "true_positives",
        "false_positives",
        "true_negatives",
        "false_negatives",
    ):
        v5_review_detector[key] = v5_review_operational[key]
    v5_review_detector["threshold"] = "frozen_v0.5_review_policy"

    stable_v5 = _action_metrics(v5_actions, y_test)
    final_linkrisk = _action_metrics(final_actions, y_test)
    transitions = _transition_stats(
        v5_actions,
        final_actions,
        y_test,
        routed.promoted_by_jane,
        routed.displaced_v5_verify,
    )

    fp_cost = []
    for unit_cost in FP_COST_SCENARIOS_INR:
        fp_cost.append(
            {
                "assumed_cost_per_legitimate_intervention_inr": unit_cost,
                "stable_v5_cost_inr": stable_v5["false_positives"] * unit_cost,
                "final_linkrisk_cost_inr": final_linkrisk["false_positives"] * unit_cost,
            }
        )

    payload: dict[str, Any] = {
        "evaluation": "final_sealed_chronological_test",
        "status": "FINAL_DO_NOT_RETUNE",
        "git_head": _git_head(),
        "protocol": {
            "model_fitting_on_test": False,
            "threshold_selection_on_test": False,
            "test_labels_used_in_prediction_features": False,
            "trusted_feedback_labels": "train+validation only, fixed 72h delay",
            "test_structural_history": "causal unlabeled train+validation+prior-test transaction history",
            "mentalist_uses_confirmed_fraud_as_input": False,
            "final_policy_is_scalar_probability": False,
            "note": (
                "v0.5 supplies a continuous risk score; Mentalist changes action routing only. "
                "Therefore PR-AUC is reported for the baseline and v0.5 risk layers, while the final "
                "LinkRisk router is evaluated by operational precision/recall/FPR/intervention metrics."
            ),
        },
        "split": {
            "train_rows": len(train),
            "validation_rows": len(validation),
            "test_rows": test_rows,
            "test_frauds": int(y_test.sum()),
            "test_fraud_rate": float(y_test.mean()),
            "test_label_digest_sha256": _label_digest(test_ids, y_test),
        },
        "frozen_policy": asdict(policy),
        "baseline_hard_detector": baseline_detector,
        "v5_hard_review_detector": v5_review_detector,
        "stable_v5_operational_policy": stable_v5,
        "final_linkrisk_operational_policy": final_linkrisk,
        "runtime_transitions": transitions,
        "mentalist_test_observability": {
            "mean_score": float(np.mean(mentalist_state.jane_scores)),
            "clue_count_0": int((mentalist_state.clue_count == 0).sum()),
            "clue_count_1": int((mentalist_state.clue_count == 1).sum()),
            "clue_count_2_plus": int((mentalist_state.clue_count >= 2).sum()),
            "promotion_rate": float(routed.promoted_by_jane.mean()),
            "displacement_rate": float(routed.displaced_v5_verify.mean()),
        },
        "false_positive_cost_sensitivity": {
            "description": (
                "Scenario analysis only; INR values are assumed operational costs per legitimate "
                "intervention, not measured Razorpay economics."
            ),
            "scenarios": fp_cost,
        },
    }

    FINAL_RESULT.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("=== FINAL HELD-OUT RESULTS ===")
    print(f"Test rows / frauds: {test_rows:,} / {int(y_test.sum()):,} ({y_test.mean():.2%})")
    print("\nBaseline hard detector")
    print(f"  precision : {baseline_detector['precision']:.4f}")
    print(f"  recall    : {baseline_detector['recall']:.4f}")
    print(f"  PR-AUC    : {baseline_detector['pr_auc']:.4f}")
    print(f"  FPR       : {baseline_detector['false_positive_rate']:.4%}")
    print(
        f"  TP/FP/TN/FN: {baseline_detector['true_positives']:,}/"
        f"{baseline_detector['false_positives']:,}/"
        f"{baseline_detector['true_negatives']:,}/"
        f"{baseline_detector['false_negatives']:,}"
    )

    print("\nv0.5 hard REVIEW detector")
    print(f"  precision : {v5_review_detector['precision']:.4f}")
    print(f"  recall    : {v5_review_detector['recall']:.4f}")
    print(f"  risk PR-AUC: {v5_review_detector['pr_auc']:.4f}")
    print(f"  FPR       : {v5_review_detector['false_positive_rate']:.4%}")

    print("\nStable v0.5 operational policy (VERIFY + REVIEW)")
    print(f"  precision : {stable_v5['precision']:.4f}")
    print(f"  recall    : {stable_v5['recall']:.4f}")
    print(f"  FPR       : {stable_v5['false_positive_rate']:.4%}")
    print(f"  intervene : {stable_v5['intervention_rate']:.2%}")

    print("\nFINAL LinkRisk operational policy (Mentalist routed)")
    print(f"  precision : {final_linkrisk['precision']:.4f}")
    print(f"  recall    : {final_linkrisk['recall']:.4f}")
    print(f"  FPR       : {final_linkrisk['false_positive_rate']:.4%}")
    print(f"  intervene : {final_linkrisk['intervention_rate']:.2%}")
    print(
        f"  TP/FP/TN/FN: {final_linkrisk['true_positives']:,}/"
        f"{final_linkrisk['false_positives']:,}/"
        f"{final_linkrisk['true_negatives']:,}/"
        f"{final_linkrisk['false_negatives']:,}"
    )

    print("\nMentalist routing")
    print(f"  promoted : {transitions['promoted_by_mentalist']['rows']:,} rows, "
          f"{transitions['promoted_by_mentalist']['frauds']:,} frauds")
    print(f"  displaced: {transitions['displaced_v5_verify']['rows']:,} rows, "
          f"{transitions['displaced_v5_verify']['frauds']:,} frauds")
    print(f"  intervention delta: {transitions['intervention_delta_rows']:+,} rows")
    print(f"  REVIEW immutable: {'YES' if transitions['v5_review_unchanged'] else 'NO'}")

    print(f"\nFINAL artifact written once: {FINAL_RESULT.relative_to(ROOT)}")
    print("Do not retune models, thresholds, clue gates, or policy from these results.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="One-shot final held-out evaluation for frozen LinkRisk."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--preflight",
        action="store_true",
        help="Check local artifacts/policy without evaluating held-out outcomes.",
    )
    mode.add_argument(
        "--execute-final",
        action="store_true",
        help="Run the one-shot final held-out evaluation and lock the aggregate result.",
    )
    args = parser.parse_args()
    if args.preflight:
        return preflight()
    return execute_final()


if __name__ == "__main__":
    raise SystemExit(main())
