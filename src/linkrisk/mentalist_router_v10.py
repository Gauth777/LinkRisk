from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ReallocationResult:
    actions: np.ndarray
    reasons: np.ndarray
    added_jane: np.ndarray
    evicted_v5_verify: np.ndarray


def reallocate_verify_capacity(
    *,
    v5_actions: np.ndarray,
    v5_risk: np.ndarray,
    jane_selected: np.ndarray,
) -> ReallocationResult:
    """Swap novel Mentalist cases into the frozen v0.5 VERIFY capacity.

    The frozen v0.5 action vector is the starting policy. Mentalist is allowed to
    add only transactions that v0.5 would ALLOW. To keep intervention count
    exactly unchanged, the same number of existing v0.5 VERIFY transactions are
    evicted, chosen by the lowest frozen v0.5 risk score.

    No outcome labels are consumed by this function. REVIEW is immutable.
    """
    actions_in = np.asarray(v5_actions, dtype=object)
    risk = np.asarray(v5_risk, dtype=float)
    jane = np.asarray(jane_selected, dtype=bool)
    n = len(actions_in)
    if len(risk) != n or len(jane) != n:
        raise ValueError("All router arrays must have equal length")

    valid = np.isin(actions_in, ["ALLOW", "VERIFY", "REVIEW"])
    if not bool(valid.all()):
        raise ValueError("v5_actions contains an unknown action")

    original_interventions = int((actions_in != "ALLOW").sum())
    review = actions_in == "REVIEW"
    verify = actions_in == "VERIFY"

    # Jane is complementary only where the complete frozen v0.5 policy would
    # otherwise take no action.
    added_jane = jane & (actions_in == "ALLOW")
    add_count = int(added_jane.sum())

    if add_count > int(verify.sum()):
        raise ValueError("Not enough v0.5 VERIFY capacity for one-for-one reallocation")

    evicted = np.zeros(n, dtype=bool)
    if add_count:
        verify_positions = np.flatnonzero(verify)
        # Lowest frozen LinkRisk risk is the weakest existing VERIFY case. Stable
        # sorting keeps ties deterministic without consulting labels.
        order = np.argsort(risk[verify_positions], kind="mergesort")
        chosen = verify_positions[order[:add_count]]
        evicted[chosen] = True

    actions = actions_in.copy()
    reasons = np.full(n, "ALLOW", dtype=object)
    reasons[review] = "V5_REVIEW"
    reasons[verify] = "V5_VERIFY_RETAINED"

    actions[evicted] = "ALLOW"
    reasons[evicted] = "V5_VERIFY_EVICTED"

    actions[added_jane] = "VERIFY"
    reasons[added_jane] = "MENTALIST_NOVEL_CASE"

    if not np.array_equal(actions[review], np.full(int(review.sum()), "REVIEW", dtype=object)):
        raise AssertionError("Frozen REVIEW decisions changed")
    if int((actions != "ALLOW").sum()) != original_interventions:
        raise AssertionError("Intervention capacity changed during reallocation")

    return ReallocationResult(
        actions=actions,
        reasons=reasons,
        added_jane=added_jane,
        evicted_v5_verify=evicted,
    )
