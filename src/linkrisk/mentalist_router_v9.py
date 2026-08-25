from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class RouterResult:
    actions: np.ndarray
    reasons: np.ndarray
    jane_cutoff: float | None
    v5_score_cutoff: float | None


def select_top_by_score(
    scores: np.ndarray,
    eligible: np.ndarray,
    limit: int,
) -> tuple[np.ndarray, float | None]:
    selected = np.zeros(len(scores), dtype=bool)
    positions = np.flatnonzero(eligible)
    if limit <= 0 or len(positions) == 0:
        return selected, None

    take = min(int(limit), len(positions))
    order = np.argsort(-scores[positions], kind="mergesort")
    chosen = positions[order[:take]]
    selected[chosen] = True
    return selected, float(np.min(scores[chosen])) if len(chosen) else None


def route_under_capacity(
    *,
    v5_review: np.ndarray,
    v5_forced_verify: np.ndarray,
    jane_candidates: np.ndarray,
    jane_scores: np.ndarray,
    v5_score_verify: np.ndarray,
    v5_risk: np.ndarray,
    total_budget_rows: int,
) -> RouterResult:
    """Route actions with a fixed evidence-priority hierarchy.

    Priority is:
      1. frozen v0.5 REVIEW;
      2. trusted v0.5 evidence overrides;
      3. Mentalist proactive investigator candidates;
      4. remaining v0.5 score-band VERIFY candidates.

    Labels are never consumed here. Capacity is operational, not outcome-tuned.
    """
    arrays = [
        v5_review,
        v5_forced_verify,
        jane_candidates,
        jane_scores,
        v5_score_verify,
        v5_risk,
    ]
    n = len(v5_review)
    if any(len(array) != n for array in arrays):
        raise ValueError("All router arrays must have equal length")
    if total_budget_rows < 0:
        raise ValueError("total_budget_rows must be non-negative")

    actions = np.full(n, "ALLOW", dtype=object)
    reasons = np.full(n, "ALLOW", dtype=object)

    review = np.asarray(v5_review, dtype=bool)
    actions[review] = "REVIEW"
    reasons[review] = "V5_REVIEW"

    fixed_verify = np.asarray(v5_forced_verify, dtype=bool) & (~review)
    fixed_count = int(review.sum() + fixed_verify.sum())
    if fixed_count > total_budget_rows:
        raise ValueError(
            "Frozen REVIEW plus trusted VERIFY overrides exceed intervention capacity"
        )

    actions[fixed_verify] = "VERIFY"
    reasons[fixed_verify] = "TRUSTED_FRAUD_OVERRIDE"

    remaining = total_budget_rows - int((actions != "ALLOW").sum())
    jane_eligible = np.asarray(jane_candidates, dtype=bool) & (actions == "ALLOW")
    jane_selected, jane_cutoff = select_top_by_score(
        np.asarray(jane_scores, dtype=float),
        jane_eligible,
        remaining,
    )
    actions[jane_selected] = "VERIFY"
    reasons[jane_selected] = "MENTALIST_PROACTIVE"

    remaining = total_budget_rows - int((actions != "ALLOW").sum())
    score_eligible = np.asarray(v5_score_verify, dtype=bool) & (actions == "ALLOW")
    score_selected, v5_score_cutoff = select_top_by_score(
        np.asarray(v5_risk, dtype=float),
        score_eligible,
        remaining,
    )
    actions[score_selected] = "VERIFY"
    reasons[score_selected] = "V5_SCORE_VERIFY"

    return RouterResult(
        actions=actions,
        reasons=reasons,
        jane_cutoff=jane_cutoff,
        v5_score_cutoff=v5_score_cutoff,
    )
