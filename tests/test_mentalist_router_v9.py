import numpy as np

from linkrisk.mentalist_router_v9 import route_under_capacity, select_top_by_score


def test_select_top_by_score_respects_capacity_and_ranking():
    scores = np.array([0.1, 0.9, 0.8, 0.7])
    eligible = np.array([True, True, False, True])
    selected, cutoff = select_top_by_score(scores, eligible, 2)

    assert selected.tolist() == [False, True, False, True]
    assert np.isclose(cutoff, 0.7)


def test_router_preserves_review_and_trusted_priority_before_jane():
    n = 8
    result = route_under_capacity(
        v5_review=np.array([1, 1, 0, 0, 0, 0, 0, 0], dtype=bool),
        v5_forced_verify=np.array([0, 0, 1, 1, 0, 0, 0, 0], dtype=bool),
        jane_candidates=np.array([0, 0, 0, 0, 1, 1, 1, 0], dtype=bool),
        jane_scores=np.array([0.0, 0.0, 0.0, 0.0, 0.7, 0.95, 0.8, 0.0]),
        v5_score_verify=np.array([0, 0, 0, 0, 0, 0, 0, 1], dtype=bool),
        v5_risk=np.array([0.9, 0.9, 0.7, 0.7, 0.6, 0.6, 0.6, 0.82]),
        total_budget_rows=6,
    )

    assert result.actions.tolist() == [
        "REVIEW",
        "REVIEW",
        "VERIFY",
        "VERIFY",
        "ALLOW",
        "VERIFY",
        "VERIFY",
        "ALLOW",
    ]
    assert result.reasons[2] == "TRUSTED_FRAUD_OVERRIDE"
    assert result.reasons[5] == "MENTALIST_PROACTIVE"
    assert result.reasons[6] == "MENTALIST_PROACTIVE"
    assert np.isclose(result.jane_cutoff, 0.8)


def test_router_uses_v5_score_band_only_for_remaining_capacity():
    result = route_under_capacity(
        v5_review=np.array([1, 0, 0, 0, 0, 0], dtype=bool),
        v5_forced_verify=np.array([0, 1, 0, 0, 0, 0], dtype=bool),
        jane_candidates=np.array([0, 0, 1, 0, 0, 0], dtype=bool),
        jane_scores=np.array([0.0, 0.0, 0.9, 0.0, 0.0, 0.0]),
        v5_score_verify=np.array([0, 0, 0, 1, 1, 1], dtype=bool),
        v5_risk=np.array([0.95, 0.7, 0.6, 0.81, 0.83, 0.79]),
        total_budget_rows=5,
    )

    assert result.actions.tolist() == [
        "REVIEW",
        "VERIFY",
        "VERIFY",
        "VERIFY",
        "VERIFY",
        "ALLOW",
    ]
    assert result.reasons[2] == "MENTALIST_PROACTIVE"
    assert result.reasons[4] == "V5_SCORE_VERIFY"
    assert result.reasons[3] == "V5_SCORE_VERIFY"
    assert np.isclose(result.v5_score_cutoff, 0.81)
