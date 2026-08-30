from __future__ import annotations

import numpy as np

from linkrisk.cost_aware_router_v2 import evidence_gate, route_cost_aware


def test_evidence_gate_only_invokes_mentalist_for_allow_with_two_clues() -> None:
    actions = np.array(["ALLOW", "ALLOW", "VERIFY", "REVIEW", "ALLOW"], dtype=object)
    baseline = np.array([0.2, 0.2, 0.2, 0.9, 0.9])
    clues = np.array([2, 1, 3, 4, 3])

    gate = evidence_gate(
        v5_actions=actions,
        baseline_risk=baseline,
        clue_count=clues,
        min_clue_families=2,
        baseline_review_threshold=0.85,
    )

    assert gate.tolist() == [True, False, False, False, False]


def test_cost_router_enforces_budget_and_preserves_review() -> None:
    actions = np.array(
        ["REVIEW", "VERIFY", "VERIFY", "VERIFY", "ALLOW", "ALLOW", "ALLOW", "ALLOW"],
        dtype=object,
    )
    v5_risk = np.array([0.9, 0.8, 0.7, 0.6, 0.1, 0.1, 0.1, 0.1])
    jane_scores = np.array([np.nan, np.nan, np.nan, np.nan, 0.95, 0.90, 0.85, 0.80])
    candidates = np.array([False, False, False, False, True, True, True, True])

    routed = route_cost_aware(
        v5_actions=actions,
        v5_risk=v5_risk,
        mentalist_scores=jane_scores,
        mentalist_candidates=candidates,
        total_budget_rows=4,
        mentalist_reservation_rows=2,
    )

    assert routed.actions[0] == "REVIEW"
    assert routed.intervention_rows == 4
    assert routed.mentalist_selected.tolist() == [False, False, False, False, True, True, False, False]
    assert routed.v5_verify_selected.tolist() == [False, True, False, False, False, False, False, False]


def test_review_can_exceed_budget_but_is_never_dropped() -> None:
    actions = np.array(["REVIEW", "REVIEW", "REVIEW", "VERIFY", "ALLOW"], dtype=object)
    routed = route_cost_aware(
        v5_actions=actions,
        v5_risk=np.array([0.9, 0.9, 0.9, 0.8, 0.1]),
        mentalist_scores=np.array([np.nan, np.nan, np.nan, np.nan, 0.95]),
        mentalist_candidates=np.array([False, False, False, False, True]),
        total_budget_rows=2,
        mentalist_reservation_rows=1,
    )

    assert routed.actions.tolist() == ["REVIEW", "REVIEW", "REVIEW", "ALLOW", "ALLOW"]
    assert routed.mandatory_review_rows == 3
    assert routed.intervention_rows == 3


def test_router_never_promotes_non_candidate_allow() -> None:
    actions = np.array(["ALLOW", "ALLOW", "VERIFY"], dtype=object)
    routed = route_cost_aware(
        v5_actions=actions,
        v5_risk=np.array([0.1, 0.2, 0.8]),
        mentalist_scores=np.array([0.99, 0.98, np.nan]),
        mentalist_candidates=np.array([False, True, False]),
        total_budget_rows=2,
        mentalist_reservation_rows=1,
    )

    assert routed.actions.tolist() == ["ALLOW", "VERIFY", "VERIFY"]
