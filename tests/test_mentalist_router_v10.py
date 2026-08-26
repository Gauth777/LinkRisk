import numpy as np

from linkrisk.mentalist_router_v10 import reallocate_verify_capacity


def test_reallocation_keeps_review_and_capacity():
    actions = np.array(["REVIEW", "VERIFY", "VERIFY", "ALLOW", "ALLOW"], dtype=object)
    risk = np.array([0.95, 0.80, 0.40, 0.30, 0.20])
    jane = np.array([False, False, False, True, False])

    result = reallocate_verify_capacity(v5_actions=actions, v5_risk=risk, jane_selected=jane)

    assert result.actions.tolist() == ["REVIEW", "VERIFY", "ALLOW", "VERIFY", "ALLOW"]
    assert int((result.actions != "ALLOW").sum()) == int((actions != "ALLOW").sum())
    assert result.actions[0] == "REVIEW"


def test_reallocation_evicts_lowest_risk_verify_first():
    actions = np.array(["VERIFY", "VERIFY", "VERIFY", "ALLOW", "ALLOW"], dtype=object)
    risk = np.array([0.70, 0.20, 0.50, 0.10, 0.11])
    jane = np.array([False, False, False, True, True])

    result = reallocate_verify_capacity(v5_actions=actions, v5_risk=risk, jane_selected=jane)

    assert result.evicted_v5_verify.tolist() == [False, True, True, False, False]
    assert result.added_jane.tolist() == [False, False, False, True, True]


def test_reallocation_only_adds_jane_cases_v5_would_allow():
    actions = np.array(["REVIEW", "VERIFY", "ALLOW", "ALLOW"], dtype=object)
    risk = np.array([0.95, 0.30, 0.20, 0.10])
    jane = np.array([True, True, True, False])

    result = reallocate_verify_capacity(v5_actions=actions, v5_risk=risk, jane_selected=jane)

    assert result.added_jane.tolist() == [False, False, True, False]
    assert result.actions[0] == "REVIEW"
    assert result.actions[2] == "VERIFY"


def test_reallocation_is_deterministic_for_equal_risk_ties():
    actions = np.array(["VERIFY", "VERIFY", "ALLOW"], dtype=object)
    risk = np.array([0.20, 0.20, 0.10])
    jane = np.array([False, False, True])

    result = reallocate_verify_capacity(v5_actions=actions, v5_risk=risk, jane_selected=jane)

    assert result.evicted_v5_verify.tolist() == [True, False, False]
