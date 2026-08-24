import math

from linkrisk.decision import RiskAction, score_transaction


def _codes(decision):
    return {item.code for item in decision.evidence}


def test_cold_start_high_ml_risk_still_reviews_via_exact_fallback():
    decision = score_transaction(
        baseline_risk=0.90,
        specialist_risk=None,
        graph_confidence=0.0,
        feedback={},
    )

    assert math.isclose(decision.linkrisk_risk, 0.90)
    assert decision.model_path == "baseline_fallback"
    assert decision.action == RiskAction.REVIEW
    assert "ML_ONLY_FALLBACK" in _codes(decision)


def test_shared_context_without_fraud_evidence_does_not_create_friction():
    decision = score_transaction(
        baseline_risk=0.18,
        specialist_risk=0.24,
        graph_confidence=0.90,
        feedback={
            "confirmed_fraud_channels": 0,
            "any_strong_confirmed_fraud": 0,
            "max_confirmed_fraud_rate": 0.0,
            "feedback_total_support_log": 4.0,
        },
    )

    assert decision.action == RiskAction.ALLOW
    assert "STRONG_FRAUD_LINK" not in _codes(decision)
    assert "CORROBORATING_FRAUD_CHANNELS" not in _codes(decision)


def test_high_support_mostly_legitimate_history_is_not_treated_as_high_fraud_rate():
    decision = score_transaction(
        baseline_risk=0.20,
        specialist_risk=0.21,
        graph_confidence=0.85,
        feedback={
            "confirmed_fraud_channels": 0,
            "max_confirmed_fraud_rate": 0.02,
            "feedback_total_support_log": 5.0,
        },
    )

    assert decision.action == RiskAction.ALLOW
    assert "ELEVATED_HISTORICAL_FRAUD_RATE" not in _codes(decision)


def test_stale_single_channel_history_is_explained_but_not_forced_to_verify():
    decision = score_transaction(
        baseline_risk=0.20,
        specialist_risk=0.25,
        graph_confidence=0.60,
        feedback={
            "confirmed_fraud_channels": 1,
            "profile_has_confirmed_fraud": 1,
            "log_profile_confirmed_fraud_30d": 0.0,
            "any_strong_confirmed_fraud": 0,
        },
    )

    codes = _codes(decision)
    assert decision.action == RiskAction.ALLOW
    assert "PROFILE_FRAUD_HISTORY" in codes
    assert "RECENT_PROFILE_FRAUD" not in codes


def test_single_weak_fraud_channel_does_not_force_verify():
    decision = score_transaction(
        baseline_risk=0.22,
        specialist_risk=0.30,
        graph_confidence=0.40,
        feedback={
            "confirmed_fraud_channels": 1,
            "any_strong_confirmed_fraud": 0,
        },
    )

    assert decision.action == RiskAction.ALLOW
    assert "SINGLE_FRAUD_CHANNEL" in _codes(decision)


def test_multiple_corroborating_channels_force_verify_not_review():
    decision = score_transaction(
        baseline_risk=0.15,
        specialist_risk=0.30,
        graph_confidence=0.80,
        feedback={
            "confirmed_fraud_channels": 2,
            "any_strong_confirmed_fraud": 0,
        },
    )

    assert decision.linkrisk_risk < 0.781202555
    assert decision.action == RiskAction.VERIFY
    assert "CORROBORATING_FRAUD_CHANNELS" in _codes(decision)


def test_strong_fraud_link_with_low_ml_risk_forces_verify_but_never_review():
    decision = score_transaction(
        baseline_risk=0.10,
        specialist_risk=0.40,
        graph_confidence=0.60,
        feedback={
            "confirmed_fraud_channels": 1,
            "any_strong_confirmed_fraud": 1,
        },
    )

    assert decision.linkrisk_risk < 0.781202555
    assert decision.action == RiskAction.VERIFY
    assert "STRONG_FRAUD_LINK" in _codes(decision)


def test_broad_relationship_confidence_alone_cannot_force_review():
    decision = score_transaction(
        baseline_risk=0.25,
        specialist_risk=0.45,
        graph_confidence=0.95,
        feedback={
            "confirmed_fraud_channels": 0,
            "any_strong_confirmed_fraud": 0,
        },
    )

    assert decision.linkrisk_risk < 0.781202555
    assert decision.action == RiskAction.ALLOW
