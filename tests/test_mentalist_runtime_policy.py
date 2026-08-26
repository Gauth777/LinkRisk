from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from linkrisk.mentalist_runtime_policy import (
    MentalistRuntimePolicy,
    MentalistState,
    apply_runtime_policy,
)


def _policy() -> MentalistRuntimePolicy:
    return MentalistRuntimePolicy(
        version="test",
        min_clue_families=2,
        jane_score_threshold=0.80,
        baseline_review_threshold=0.85,
        v5_verify_displacement_threshold=0.20,
        validation_intervention_target=0.06,
    )


def _state(scores: list[float], clues: list[int]) -> MentalistState:
    frame = pd.DataFrame({"independent_clue_count": clues})
    return MentalistState(
        jane_scores=np.asarray(scores, dtype=float),
        clue_count=np.asarray(clues, dtype=int),
        clue_frame=frame,
    )


def test_review_is_immutable() -> None:
    result = apply_runtime_policy(
        v5_actions=np.asarray(["REVIEW"], dtype=object),
        v5_risk=np.asarray([0.95]),
        baseline_risk=np.asarray([0.95]),
        mentalist_state=_state([0.99], [4]),
        policy=_policy(),
    )
    assert result.actions.tolist() == ["REVIEW"]
    assert not result.promoted_by_jane.any()
    assert not result.displaced_v5_verify.any()


def test_jane_promotes_only_corroborated_allow() -> None:
    result = apply_runtime_policy(
        v5_actions=np.asarray(["ALLOW", "ALLOW", "ALLOW"], dtype=object),
        v5_risk=np.asarray([0.40, 0.40, 0.40]),
        baseline_risk=np.asarray([0.40, 0.40, 0.40]),
        mentalist_state=_state([0.90, 0.90, 0.70], [2, 1, 3]),
        policy=_policy(),
    )
    assert result.actions.tolist() == ["VERIFY", "ALLOW", "ALLOW"]
    assert result.promoted_by_jane.tolist() == [True, False, False]


def test_baseline_review_boundary_blocks_jane_promotion() -> None:
    result = apply_runtime_policy(
        v5_actions=np.asarray(["ALLOW", "ALLOW"], dtype=object),
        v5_risk=np.asarray([0.40, 0.40]),
        baseline_risk=np.asarray([0.90, 0.84]),
        mentalist_state=_state([0.95, 0.95], [3, 3]),
        policy=_policy(),
    )
    assert result.actions.tolist() == ["ALLOW", "VERIFY"]
    assert result.promoted_by_jane.tolist() == [False, True]


def test_weak_v5_verify_is_displaced_by_fixed_boundary() -> None:
    result = apply_runtime_policy(
        v5_actions=np.asarray(["VERIFY", "VERIFY"], dtype=object),
        v5_risk=np.asarray([0.10, 0.30]),
        baseline_risk=np.asarray([0.10, 0.30]),
        mentalist_state=_state([0.10, 0.10], [0, 0]),
        policy=_policy(),
    )
    assert result.actions.tolist() == ["ALLOW", "VERIFY"]
    assert result.displaced_v5_verify.tolist() == [True, False]


def test_runtime_policy_reports_intervention_delta() -> None:
    result = apply_runtime_policy(
        v5_actions=np.asarray(["ALLOW", "VERIFY", "ALLOW"], dtype=object),
        v5_risk=np.asarray([0.10, 0.10, 0.10]),
        baseline_risk=np.asarray([0.10, 0.10, 0.10]),
        mentalist_state=_state([0.90, 0.10, 0.85], [2, 0, 2]),
        policy=_policy(),
    )
    assert int(result.promoted_by_jane.sum()) == 2
    assert int(result.displaced_v5_verify.sum()) == 1
    assert result.intervention_delta == 1


def test_runtime_policy_rejects_misaligned_arrays() -> None:
    with pytest.raises(ValueError):
        apply_runtime_policy(
            v5_actions=np.asarray(["ALLOW", "VERIFY"], dtype=object),
            v5_risk=np.asarray([0.1]),
            baseline_risk=np.asarray([0.1, 0.2]),
            mentalist_state=_state([0.9, 0.1], [2, 0]),
            policy=_policy(),
        )
