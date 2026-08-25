import pytest

from linkrisk.decision import RiskAction
from linkrisk.demo import demo_scenarios, evaluate_scenario


def scenarios_by_key():
    return {scenario.key: scenario for scenario in demo_scenarios()}


def test_demo_scenario_keys_are_unique():
    scenarios = demo_scenarios()
    assert len({scenario.key for scenario in scenarios}) == len(scenarios)


@pytest.mark.parametrize(
    ("key", "expected_action"),
    [
        ("cold_start", RiskAction.ALLOW),
        ("benign_shared", RiskAction.ALLOW),
        ("score_verify", RiskAction.VERIFY),
        ("strong_verify", RiskAction.VERIFY),
        ("coordinated_review", RiskAction.REVIEW),
        ("ml_high_risk", RiskAction.REVIEW),
    ],
)
def test_guided_scenarios_follow_frozen_policy(key, expected_action):
    decision = evaluate_scenario(scenarios_by_key()[key])
    assert decision.action == expected_action


def test_cold_start_demo_preserves_exact_baseline_fallback():
    scenario = scenarios_by_key()["cold_start"]
    decision = evaluate_scenario(scenario)
    assert decision.linkrisk_risk == scenario.baseline_risk
    assert decision.model_path == "baseline_fallback"
    assert decision.evidence[0].code == "ML_ONLY_FALLBACK"


def test_strong_link_demo_forces_verify_without_review():
    decision = evaluate_scenario(scenarios_by_key()["strong_verify"])
    assert decision.action == RiskAction.VERIFY
    assert any(item.code == "STRONG_FRAUD_LINK" for item in decision.evidence)


def test_coordinated_demo_contains_corroborating_evidence():
    decision = evaluate_scenario(scenarios_by_key()["coordinated_review"])
    codes = {item.code for item in decision.evidence}
    assert decision.action == RiskAction.REVIEW
    assert "STRONG_FRAUD_LINK" in codes
    assert "CORROBORATING_FRAUD_CHANNELS" in codes
