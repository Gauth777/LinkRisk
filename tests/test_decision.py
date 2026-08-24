import pytest

from linkrisk.decision import (
    REVIEW_THRESHOLD,
    VERIFY_THRESHOLD,
    RiskAction,
    score_transaction,
)


def test_exact_fallback_uses_baseline_and_allow():
    result = score_transaction(
        baseline_risk=0.20,
        specialist_risk=None,
        graph_confidence=0.0,
        feedback={},
        transaction_id="t-1",
    )

    assert result.linkrisk_risk == 0.20
    assert result.action == RiskAction.ALLOW
    assert result.model_path == "baseline_fallback"
    assert result.evidence[0].code == "ML_ONLY_FALLBACK"


def test_review_uses_frozen_v05_threshold():
    result = score_transaction(
        baseline_risk=0.80,
        specialist_risk=0.90,
        graph_confidence=1.0,
        feedback={},
    )

    assert result.linkrisk_risk == pytest.approx(0.90)
    assert result.linkrisk_risk >= REVIEW_THRESHOLD
    assert result.action == RiskAction.REVIEW


def test_verify_score_band_is_below_review():
    result = score_transaction(
        baseline_risk=VERIFY_THRESHOLD,
        specialist_risk=None,
        graph_confidence=0.0,
        feedback={},
    )

    assert result.action == RiskAction.VERIFY


def test_strong_matured_fraud_link_can_force_verify_not_review():
    result = score_transaction(
        baseline_risk=0.30,
        specialist_risk=0.45,
        graph_confidence=0.60,
        feedback={"any_strong_confirmed_fraud": 1.0},
    )

    assert result.linkrisk_risk < VERIFY_THRESHOLD
    assert result.action == RiskAction.VERIFY
    assert any(item.code == "STRONG_FRAUD_LINK" for item in result.evidence)


def test_corroborating_channels_are_explained():
    result = score_transaction(
        baseline_risk=0.25,
        specialist_risk=0.40,
        graph_confidence=0.80,
        feedback={
            "confirmed_fraud_channels": 2,
            "profile_has_confirmed_fraud": 1,
            "log_profile_confirmed_fraud_30d": 0.69,
            "max_confirmed_fraud_rate": 0.50,
            "feedback_total_support_log": 1.61,
        },
    )

    codes = {item.code for item in result.evidence}
    assert result.action == RiskAction.VERIFY
    assert "CORROBORATING_FRAUD_CHANNELS" in codes
    assert "RECENT_PROFILE_FRAUD" in codes


def test_low_risk_context_without_strong_evidence_allows():
    result = score_transaction(
        baseline_risk=0.15,
        specialist_risk=0.20,
        graph_confidence=0.30,
        feedback={"confirmed_fraud_channels": 0},
    )

    assert result.action == RiskAction.ALLOW
    assert result.model_path == "feedback_specialist_v0.5"


def test_invalid_score_is_rejected():
    with pytest.raises(ValueError):
        score_transaction(
            baseline_risk=1.2,
            specialist_risk=None,
            graph_confidence=0.0,
            feedback={},
        )
