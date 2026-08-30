from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from linkrisk.mentalist_router_v9 import select_top_by_score


@dataclass(frozen=True)
class CostAwareRoutingResult:
    actions: np.ndarray
    reasons: np.ndarray
    mentalist_selected: np.ndarray
    v5_verify_selected: np.ndarray
    intervention_budget_rows: int
    mandatory_review_rows: int
    mentalist_reservation_rows: int

    @property
    def intervention_rows(self) -> int:
        return int((self.actions != "ALLOW").sum())

    @property
    def unused_capacity_rows(self) -> int:
        return max(self.intervention_budget_rows - self.intervention_rows, 0)


def evidence_gate(
    *,
    v5_actions: np.ndarray,
    baseline_risk: np.ndarray,
    clue_count: np.ndarray,
    min_clue_families: int,
    baseline_review_threshold: float,
) -> np.ndarray:
    """Return rows worth invoking the proactive Mentalist model on.

    This is intentionally cheap and label-free. Mentalist is complementary only
    where v0.5 would otherwise ALLOW, the transaction-only baseline is below the
    frozen hard-review boundary, and at least the frozen number of independent
    clue families are present.
    """
    actions = np.asarray(v5_actions, dtype=object)
    baseline = np.asarray(baseline_risk, dtype=float)
    clues = np.asarray(clue_count, dtype=int)
    n = len(actions)
    if len(baseline) != n or len(clues) != n:
        raise ValueError("All evidence-gate arrays must have equal length")
    if min_clue_families < 1:
        raise ValueError("min_clue_families must be >= 1")

    return (
        (actions == "ALLOW")
        & (baseline < float(baseline_review_threshold))
        & (clues >= int(min_clue_families))
    )


def route_cost_aware(
    *,
    v5_actions: np.ndarray,
    v5_risk: np.ndarray,
    mentalist_scores: np.ndarray,
    mentalist_candidates: np.ndarray,
    total_budget_rows: int,
    mentalist_reservation_rows: int,
) -> CostAwareRoutingResult:
    """Allocate scarce intervention capacity without using outcome labels.

    Priority:
      1. frozen v0.5 REVIEW is immutable and mandatory;
      2. reserve up to a fixed number of slots for strongest proactive Mentalist
         candidates;
      3. fill remaining capacity with strongest frozen v0.5 VERIFY candidates.

    Unlike the v1.0 scalar runtime approximation, the total capacity is explicit.
    If mandatory REVIEW alone exceeds the declared budget, REVIEW is preserved and
    the budget is necessarily exceeded; safety takes precedence over capacity.
    """
    actions_in = np.asarray(v5_actions, dtype=object)
    risk = np.asarray(v5_risk, dtype=float)
    jane = np.asarray(mentalist_scores, dtype=float)
    candidates = np.asarray(mentalist_candidates, dtype=bool)
    n = len(actions_in)
    if any(len(array) != n for array in (risk, jane, candidates)):
        raise ValueError("All router arrays must have equal length")
    if total_budget_rows < 0 or mentalist_reservation_rows < 0:
        raise ValueError("Budget values must be non-negative")

    valid = np.isin(actions_in, ["ALLOW", "VERIFY", "REVIEW"])
    if not bool(valid.all()):
        raise ValueError("v5_actions contains an unknown action")

    review = actions_in == "REVIEW"
    verify = actions_in == "VERIFY"
    mandatory_count = int(review.sum())

    actions = np.full(n, "ALLOW", dtype=object)
    reasons = np.full(n, "ALLOW_CAPACITY", dtype=object)
    actions[review] = "REVIEW"
    reasons[review] = "V5_REVIEW_MANDATORY"

    # REVIEW is never sacrificed to satisfy an operational budget.
    effective_budget = max(int(total_budget_rows), mandatory_count)
    remaining = effective_budget - mandatory_count

    jane_eligible = candidates & (actions_in == "ALLOW") & np.isfinite(jane)
    jane_limit = min(int(mentalist_reservation_rows), remaining)
    jane_selected, _ = select_top_by_score(jane, jane_eligible, jane_limit)
    actions[jane_selected] = "VERIFY"
    reasons[jane_selected] = "MENTALIST_RESERVED_VERIFY"

    remaining = effective_budget - int((actions != "ALLOW").sum())
    v5_eligible = verify & (actions == "ALLOW")
    v5_selected, _ = select_top_by_score(risk, v5_eligible, remaining)
    actions[v5_selected] = "VERIFY"
    reasons[v5_selected] = "V5_RISK_VERIFY"

    if not bool(np.all(actions[review] == "REVIEW")):
        raise AssertionError("Frozen v0.5 REVIEW decision changed")
    if mandatory_count <= total_budget_rows and int((actions != "ALLOW").sum()) > total_budget_rows:
        raise AssertionError("Intervention budget exceeded")

    return CostAwareRoutingResult(
        actions=actions,
        reasons=reasons,
        mentalist_selected=jane_selected,
        v5_verify_selected=v5_selected,
        intervention_budget_rows=int(total_budget_rows),
        mandatory_review_rows=mandatory_count,
        mentalist_reservation_rows=int(mentalist_reservation_rows),
    )
