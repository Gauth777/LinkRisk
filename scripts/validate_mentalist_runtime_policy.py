from __future__ import annotations

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from linkrisk.baseline import BASE_RAW_FEATURES, ID_COL, TARGET, TIME_COL, merge_transaction_identity
from linkrisk.data import chronological_split
from linkrisk.engine import FrozenChampionScorer
from linkrisk.feedback_features_v5 import build_feedback_features_v5
from linkrisk.mentalist_features_v7 import build_mentalist_features_v7
from linkrisk.mentalist_router_v10 import reallocate_verify_capacity
from linkrisk.mentalist_router_v9 import select_top_by_score
from linkrisk.mentalist_runtime_policy import (
    FrozenMentalistScorer,
    apply_runtime_policy,
)
from linkrisk.relationship_features_v4 import build_relationship_features_v4

DATA_DIR = ROOT / "data" / "raw"
RESULTS_DIR = ROOT / "artifacts" / "results"
JANE_RESERVATION = 0.0100


def load_data() -> pd.DataFrame:
    tx_path = DATA_DIR / "train_transaction.csv"
    id_path = DATA_DIR / "train_identity.csv"
    required_tx = {ID_COL, TIME_COL, TARGET, *BASE_RAW_FEATURES}
    required_id = {ID_COL, *BASE_RAW_FEATURES}
    tx = pd.read_csv(tx_path, usecols=lambda c: c in required_tx, low_memory=False)
    identity = pd.read_csv(id_path, usecols=lambda c: c in required_id, low_memory=False)
    return merge_transaction_identity(tx, identity)


def metrics(actions: np.ndarray, y: np.ndarray) -> dict[str, float | int]:
    intervene = actions != "ALLOW"
    total_fraud = int((y == 1).sum())
    total_legit = int((y == 0).sum())
    frauds = int(((y == 1) & intervene).sum())
    legit = int(((y == 0) & intervene).sum())
    return {
        "intervention_rows": int(intervene.sum()),
        "intervention_share": float(intervene.mean()),
        "fraud_capture": frauds / total_fraud if total_fraud else 0.0,
        "legitimate_friction": legit / total_legit if total_legit else 0.0,
    }


def main() -> None:
    print("Loading IEEE-CIS development data...")
    data = load_data()
    train, validation, sealed_test = chronological_split(data)
    sealed_rows = len(sealed_test)
    del sealed_test
    del data

    print("Building causal proactive and trusted-memory state across train -> validation...")
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

    champion = FrozenChampionScorer.from_artifacts(ROOT)
    mentalist = FrozenMentalistScorer.from_artifacts(ROOT)

    v5 = champion.score_batch(validation, val_relationship, val_feedback)
    v5_actions = v5["action"].astype(str).to_numpy()
    v5_risk = v5["linkrisk_risk"].to_numpy(dtype=float)
    baseline_risk = v5["baseline_risk"].to_numpy(dtype=float)

    state = mentalist.score_batch(val_proactive, baseline_risk)
    runtime = apply_runtime_policy(
        v5_actions=v5_actions,
        v5_risk=v5_risk,
        baseline_risk=baseline_risk,
        mentalist_state=state,
        policy=mentalist.policy,
    )

    # Reconstruct the successful v1.0 batch allocation exactly. The Mentalist
    # candidate pool is defined against the frozen transaction-baseline REVIEW
    # boundary, not the final v0.5 REVIEW mask.
    baseline_review = baseline_risk >= mentalist.policy.baseline_review_threshold
    jane_eligible = (
        (~baseline_review)
        & (state.clue_count >= mentalist.policy.min_clue_families)
    )
    jane_target_rows = int(round(len(validation) * JANE_RESERVATION))
    jane_selected, _ = select_top_by_score(
        state.jane_scores,
        jane_eligible,
        jane_target_rows,
    )
    batch = reallocate_verify_capacity(
        v5_actions=v5_actions,
        v5_risk=v5_risk,
        jane_selected=jane_selected,
    )

    y = validation[TARGET].astype(np.int8).to_numpy()
    stable_metrics = metrics(v5_actions, y)
    batch_metrics = metrics(batch.actions, y)
    runtime_metrics = metrics(runtime.actions, y)

    mismatch = runtime.actions != batch.actions
    mismatch_count = int(mismatch.sum())
    action_agreement = 1.0 - mismatch_count / len(validation)
    review_immutable = bool(np.all(runtime.actions[v5_actions == "REVIEW"] == "REVIEW"))
    same_capacity_as_batch = (
        runtime_metrics["intervention_rows"] == batch_metrics["intervention_rows"]
    )
    exact_reproduction = bool(mismatch_count == 0)
    passed = bool(exact_reproduction and review_immutable and same_capacity_as_batch)

    # Boundary diagnostics remain label-free. If the gate still fails, they tell
    # us whether the only remaining issue is a score tie at one of the cutoffs.
    jane_at_boundary = (
        (np.abs(state.jane_scores - mentalist.policy.jane_score_threshold) <= 1e-12)
        & jane_eligible
    )
    displacement_at_boundary = (
        (np.abs(v5_risk - mentalist.policy.v5_verify_displacement_threshold) <= 1e-12)
        & (v5_actions == "VERIFY")
    )

    print("\n=== Mentalist Runtime Reproduction Check ===")
    print(f"Held-out test rows: {sealed_rows:,} (deleted before evaluation)")
    print(f"Jane fixed threshold:              {mentalist.policy.jane_score_threshold:.15f}")
    print(f"Baseline REVIEW threshold:         {mentalist.policy.baseline_review_threshold:.15f}")
    print(f"v0.5 displacement threshold:      {mentalist.policy.v5_verify_displacement_threshold:.15f}")
    print(f"Runtime Jane promotions:           {int(runtime.promoted_by_jane.sum()):,}")
    print(f"Runtime v0.5 VERIFY displacements: {int(runtime.displaced_v5_verify.sum()):,}")
    print(f"Runtime intervention delta:        {runtime.intervention_delta:+d}")
    print(f"Action agreement vs v1.0 batch:    {100*action_agreement:.6f}%")
    print(f"Action mismatches:                 {mismatch_count:,}")
    print(f"Jane candidates exactly at cutoff: {int(jane_at_boundary.sum()):,}")
    print(f"VERIFY cases exactly at cutoff:    {int(displacement_at_boundary.sum()):,}")

    print("\nStable v0.5")
    print(f"  intervention: {100*stable_metrics['intervention_share']:.2f}%")
    print(f"  fraud capture:{100*stable_metrics['fraud_capture']:.2f}%")
    print(f"  legit friction:{100*stable_metrics['legitimate_friction']:.2f}%")

    print("\nSuccessful v1.0 batch policy")
    print(f"  intervention: {100*batch_metrics['intervention_share']:.2f}%")
    print(f"  fraud capture:{100*batch_metrics['fraud_capture']:.2f}%")
    print(f"  legit friction:{100*batch_metrics['legitimate_friction']:.2f}%")

    print("\nFixed per-transaction runtime policy")
    print(f"  intervention: {100*runtime_metrics['intervention_share']:.2f}%")
    print(f"  fraud capture:{100*runtime_metrics['fraud_capture']:.2f}%")
    print(f"  legit friction:{100*runtime_metrics['legitimate_friction']:.2f}%")

    print("\nRuntime freeze gate")
    print(f"  exact v1.0 action reproduction: {'YES' if exact_reproduction else 'NO'}")
    print(f"  REVIEW immutable:               {'YES' if review_immutable else 'NO'}")
    print(f"  same intervention capacity:     {'YES' if same_capacity_as_batch else 'NO'}")
    print(f"  Candidate status:               {'PASS' if passed else 'FAIL'}")

    out = RESULTS_DIR / "mentalist_runtime_validation.json"
    payload = {
        "experiment": "mentalist_v1.0_runtime_reproduction",
        "held_out_test": {"status": "sealed", "rows": sealed_rows, "labels_used": False},
        "runtime_policy": {
            "jane_score_threshold": mentalist.policy.jane_score_threshold,
            "baseline_review_threshold": mentalist.policy.baseline_review_threshold,
            "v5_verify_displacement_threshold": mentalist.policy.v5_verify_displacement_threshold,
            "min_clue_families": mentalist.policy.min_clue_families,
        },
        "runtime_counts": {
            "jane_promotions": int(runtime.promoted_by_jane.sum()),
            "v5_verify_displacements": int(runtime.displaced_v5_verify.sum()),
            "intervention_delta": runtime.intervention_delta,
        },
        "boundary_diagnostics": {
            "jane_candidates_exactly_at_cutoff": int(jane_at_boundary.sum()),
            "v5_verify_exactly_at_displacement_cutoff": int(displacement_at_boundary.sum()),
        },
        "stable_v5": stable_metrics,
        "batch_v1": batch_metrics,
        "fixed_runtime": runtime_metrics,
        "action_mismatch_count": mismatch_count,
        "action_agreement": action_agreement,
        "gate": {
            "exact_reproduction": exact_reproduction,
            "review_immutable": review_immutable,
            "same_capacity": same_capacity_as_batch,
            "pass": passed,
        },
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nSaved {out.relative_to(ROOT)}")

    if not passed:
        print(
            "\nDo NOT open the held-out test. The fixed runtime contract still "
            "does not reproduce the successful v1.0 allocation exactly."
        )


if __name__ == "__main__":
    main()
