from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from linkrisk.baseline import BASE_RAW_FEATURES, ID_COL, TARGET, TIME_COL, merge_transaction_identity
from linkrisk.cost_aware_router_v2 import evidence_gate, route_cost_aware
from linkrisk.data import chronological_split
from linkrisk.engine import FrozenChampionScorer
from linkrisk.feedback_features_v5 import build_feedback_features_v5
from linkrisk.mentalist_features_v7 import build_mentalist_features_v7, clue_activations
from linkrisk.mentalist_runtime_policy import FrozenMentalistScorer
from linkrisk.relationship_features_v4 import build_relationship_features_v4

DATA_DIR = ROOT / "data" / "raw"
RESULTS_DIR = ROOT / "artifacts" / "results"
OUT = RESULTS_DIR / "cost_aware_v2_validation.json"

# These are carried forward from the already-frozen development design. They are
# not selected from held-out test performance.
TOTAL_INTERVENTION_RATE = 0.06
MENTALIST_RESERVATION_RATE = 0.01


def load_data() -> pd.DataFrame:
    tx_path = DATA_DIR / "train_transaction.csv"
    id_path = DATA_DIR / "train_identity.csv"
    required_tx = {ID_COL, TIME_COL, TARGET, *BASE_RAW_FEATURES}
    required_id = {ID_COL, *BASE_RAW_FEATURES}
    tx = pd.read_csv(tx_path, usecols=lambda c: c in required_tx, low_memory=False)
    identity = pd.read_csv(id_path, usecols=lambda c: c in required_id, low_memory=False)
    return merge_transaction_identity(tx, identity)


def policy_metrics(actions: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    actions = np.asarray(actions, dtype=object)
    y = np.asarray(y, dtype=np.int8)
    intervention = actions != "ALLOW"
    tp = int(((y == 1) & intervention).sum())
    fp = int(((y == 0) & intervention).sum())
    frauds = int((y == 1).sum())
    legitimate = int((y == 0).sum())
    return {
        "intervention_rows": int(intervention.sum()),
        "intervention_rate": float(intervention.mean()),
        "precision": tp / max(tp + fp, 1),
        "recall": tp / max(frauds, 1),
        "false_positive_rate": fp / max(legitimate, 1),
        "true_positives": tp,
        "false_positives": fp,
        "true_negatives": legitimate - fp,
        "false_negatives": frauds - tp,
        "review_rows": int((actions == "REVIEW").sum()),
        "verify_rows": int((actions == "VERIFY").sum()),
    }


def main() -> None:
    print("=== LinkRisk v2 — Cost-Aware Selective Investigation ===\n")
    print("DEVELOPMENT VALIDATION ONLY.")
    print("The previously opened held-out test is not evaluated, scored, or inspected here.\n")

    data = load_data()
    train, validation, sealed_test = chronological_split(data)
    sealed_test_rows = len(sealed_test)
    del sealed_test
    del data

    champion = FrozenChampionScorer.from_artifacts(ROOT)
    mentalist = FrozenMentalistScorer.from_artifacts(ROOT)
    policy = mentalist.policy

    development = pd.concat([train, validation], axis=0).sort_values(TIME_COL, kind="mergesort")

    print("Building causal development state...")
    relationship = build_relationship_features_v4(development)
    proactive = build_mentalist_features_v7(development)

    label_eligible = pd.Series(False, index=development.index, dtype=bool)
    label_eligible.loc[train.index] = True
    feedback = build_feedback_features_v5(development, label_eligible)

    val_rel = relationship.loc[validation.index]
    val_proactive = proactive.loc[validation.index]
    val_feedback = feedback.loc[validation.index]

    print("Scoring frozen v0.5 policy...")
    v5 = champion.score_batch(validation, val_rel, val_feedback)
    v5_actions = v5["action"].astype(str).to_numpy()
    v5_risk = v5["linkrisk_risk"].to_numpy(dtype=float)
    baseline_risk = v5["baseline_risk"].to_numpy(dtype=float)

    print("Applying cheap evidence gate before Mentalist inference...")
    clues = clue_activations(val_proactive, mentalist.clue_thresholds)
    clue_count = clues["independent_clue_count"].to_numpy(dtype=int)
    invoke = evidence_gate(
        v5_actions=v5_actions,
        baseline_risk=baseline_risk,
        clue_count=clue_count,
        min_clue_families=policy.min_clue_families,
        baseline_review_threshold=policy.baseline_review_threshold,
    )

    jane_scores = np.full(len(validation), np.nan, dtype=float)
    invoke_positions = np.flatnonzero(invoke)
    if len(invoke_positions):
        selective = mentalist.score_batch(
            val_proactive.iloc[invoke_positions],
            baseline_risk[invoke_positions],
        )
        jane_scores[invoke_positions] = selective.jane_scores

    jane_candidates = invoke & (jane_scores >= policy.jane_score_threshold)

    total_budget_rows = int(round(len(validation) * TOTAL_INTERVENTION_RATE))
    jane_reservation_rows = int(round(len(validation) * MENTALIST_RESERVATION_RATE))
    routed = route_cost_aware(
        v5_actions=v5_actions,
        v5_risk=v5_risk,
        mentalist_scores=jane_scores,
        mentalist_candidates=jane_candidates,
        total_budget_rows=total_budget_rows,
        mentalist_reservation_rows=jane_reservation_rows,
    )

    # Labels are consulted only after all actions above are fixed.
    y = validation[TARGET].astype(np.int8).to_numpy()
    stable = policy_metrics(v5_actions, y)
    final = policy_metrics(routed.actions, y)

    invoked_frauds = int(((y == 1) & invoke).sum())
    selected = routed.mentalist_selected
    selected_frauds = int(((y == 1) & selected).sum())
    selected_legit = int(((y == 0) & selected).sum())

    payload = {
        "experiment": "linkrisk_v2_cost_aware_selective_investigation",
        "status": "development_validation_only",
        "held_out_test": {
            "status": "previously opened; not used for v2 development evaluation",
            "rows": sealed_test_rows,
            "labels_used": False,
            "scores_computed": False,
        },
        "design": {
            "total_intervention_rate": TOTAL_INTERVENTION_RATE,
            "mentalist_reservation_rate": MENTALIST_RESERVATION_RATE,
            "min_clue_families": policy.min_clue_families,
            "jane_score_threshold": policy.jane_score_threshold,
            "review_immutable": True,
            "selection_uses_labels": False,
        },
        "selective_reasoning": {
            "rows": len(validation),
            "mentalist_invocations": int(invoke.sum()),
            "mentalist_invocation_rate": float(invoke.mean()),
            "mentalist_bypass_rate": float((~invoke).mean()),
            "frauds_in_invoked_rows": invoked_frauds,
            "candidate_rows_after_jane_threshold": int(jane_candidates.sum()),
            "reserved_mentalist_rows_selected": int(selected.sum()),
            "selected_mentalist_frauds": selected_frauds,
            "selected_mentalist_legitimate": selected_legit,
            "selected_mentalist_fraud_rate": selected_frauds / max(int(selected.sum()), 1),
        },
        "stable_v5": stable,
        "cost_aware_v2": final,
        "deltas": {
            "recall_pp": 100.0 * (final["recall"] - stable["recall"]),
            "precision_pp": 100.0 * (final["precision"] - stable["precision"]),
            "fpr_pp": 100.0 * (final["false_positive_rate"] - stable["false_positive_rate"]),
            "intervention_pp": 100.0 * (final["intervention_rate"] - stable["intervention_rate"]),
            "true_positives": final["true_positives"] - stable["true_positives"],
            "false_positives": final["false_positives"] - stable["false_positives"],
        },
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("\nSelective reasoning")
    print(f"  Mentalist invoked : {int(invoke.sum()):,} / {len(validation):,} ({invoke.mean():.2%})")
    print(f"  Mentalist bypassed: {int((~invoke).sum()):,} / {len(validation):,} ({(~invoke).mean():.2%})")
    print(f"  Jane candidates   : {int(jane_candidates.sum()):,}")
    print(f"  Jane selected     : {int(selected.sum()):,}")

    print("\nStable v0.5")
    print(f"  intervene : {stable['intervention_rate']:.2%}")
    print(f"  precision : {stable['precision']:.4f}")
    print(f"  recall    : {stable['recall']:.4f}")
    print(f"  FPR       : {stable['false_positive_rate']:.4%}")
    print(f"  TP / FP   : {stable['true_positives']:,} / {stable['false_positives']:,}")

    print("\nCost-aware v2")
    print(f"  budget    : {total_budget_rows:,} rows ({TOTAL_INTERVENTION_RATE:.2%})")
    print(f"  intervene : {final['intervention_rate']:.2%}")
    print(f"  precision : {final['precision']:.4f}")
    print(f"  recall    : {final['recall']:.4f}")
    print(f"  FPR       : {final['false_positive_rate']:.4%}")
    print(f"  TP / FP   : {final['true_positives']:,} / {final['false_positives']:,}")

    print("\nDeltas vs stable v0.5")
    print(f"  recall      : {payload['deltas']['recall_pp']:+.2f} pp")
    print(f"  precision   : {payload['deltas']['precision_pp']:+.2f} pp")
    print(f"  FPR         : {payload['deltas']['fpr_pp']:+.2f} pp")
    print(f"  intervention: {payload['deltas']['intervention_pp']:+.2f} pp")
    print(f"  TP / FP     : {payload['deltas']['true_positives']:+d} / {payload['deltas']['false_positives']:+d}")

    print(f"\nSaved {OUT.relative_to(ROOT)}")
    print("Do not use the old held-out test to tune v2.")


if __name__ == "__main__":
    main()
