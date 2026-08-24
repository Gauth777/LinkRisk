from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import math
from typing import Any, Mapping


CHAMPION_VERSION = "v0.5"
CHAMPION_GATE_STRENGTH = 1.00
REVIEW_THRESHOLD = 0.840618
VERIFY_THRESHOLD = round(REVIEW_THRESHOLD * 0.75, 6)
STRONG_EVIDENCE_CONFIDENCE = 0.50
MULTI_CHANNEL_CONFIDENCE = 0.70


class RiskAction(str, Enum):
    ALLOW = "ALLOW"
    VERIFY = "VERIFY"
    REVIEW = "REVIEW"


@dataclass(frozen=True)
class EvidenceItem:
    code: str
    level: str
    message: str


@dataclass(frozen=True)
class RiskDecision:
    transaction_id: str | int | None
    champion_version: str
    baseline_risk: float
    specialist_risk: float | None
    linkrisk_risk: float
    graph_confidence: float
    action: RiskAction
    model_path: str
    evidence: tuple[EvidenceItem, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["action"] = self.action.value
        payload["evidence"] = [asdict(item) for item in self.evidence]
        return payload


def _unit_interval(value: float, name: str) -> float:
    numeric = float(value)
    if not 0.0 <= numeric <= 1.0:
        raise ValueError(f"{name} must lie in [0, 1]")
    return numeric


def _feedback_value(feedback: Mapping[str, Any] | None, key: str) -> float:
    if feedback is None:
        return 0.0
    value = feedback.get(key, 0.0)
    if value is None:
        return 0.0
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return numeric if math.isfinite(numeric) else 0.0


def champion_gate(
    baseline_risk: float,
    specialist_risk: float | None,
    graph_confidence: float,
) -> float:
    """Apply the frozen v0.5 confidence gate to scalar risk scores.

    Scores are ranking/risk scores, not calibrated fraud probabilities.
    Exact fallback is enforced whenever graph_confidence == 0.
    """
    baseline = _unit_interval(baseline_risk, "baseline_risk")
    confidence = _unit_interval(graph_confidence, "graph_confidence")

    if confidence == 0.0:
        return baseline
    if specialist_risk is None:
        raise ValueError("specialist_risk is required when graph_confidence > 0")

    specialist = _unit_interval(specialist_risk, "specialist_risk")
    fused = baseline + CHAMPION_GATE_STRENGTH * confidence * (specialist - baseline)
    return min(max(float(fused), 0.0), 1.0)


def decide_action(
    linkrisk_risk: float,
    graph_confidence: float,
    feedback: Mapping[str, Any] | None = None,
) -> RiskAction:
    """Map the champion risk score to a transparent operational action.

    REVIEW uses the frozen v0.5 validation operating threshold. VERIFY is a
    deliberately simple business/demo band, not a separately optimized model
    threshold. Strong matured relationship evidence may force VERIFY, but never
    REVIEW by itself.
    """
    risk = _unit_interval(linkrisk_risk, "linkrisk_risk")
    confidence = _unit_interval(graph_confidence, "graph_confidence")

    if risk >= REVIEW_THRESHOLD:
        return RiskAction.REVIEW
    if risk >= VERIFY_THRESHOLD:
        return RiskAction.VERIFY

    strong_link = _feedback_value(feedback, "any_strong_confirmed_fraud") > 0.0
    fraud_channels = _feedback_value(feedback, "confirmed_fraud_channels")

    if strong_link and confidence >= STRONG_EVIDENCE_CONFIDENCE:
        return RiskAction.VERIFY
    if fraud_channels >= 2.0 and confidence >= MULTI_CHANNEL_CONFIDENCE:
        return RiskAction.VERIFY
    return RiskAction.ALLOW


def build_evidence(
    baseline_risk: float,
    linkrisk_risk: float,
    graph_confidence: float,
    feedback: Mapping[str, Any] | None = None,
) -> tuple[EvidenceItem, ...]:
    """Create deterministic, judge-readable evidence without an LLM."""
    baseline = _unit_interval(baseline_risk, "baseline_risk")
    final = _unit_interval(linkrisk_risk, "linkrisk_risk")
    confidence = _unit_interval(graph_confidence, "graph_confidence")

    if confidence == 0.0:
        return (
            EvidenceItem(
                code="ML_ONLY_FALLBACK",
                level="info",
                message="No matured relationship feedback is available; LinkRisk uses the transaction-only baseline exactly.",
            ),
        )

    items: list[EvidenceItem] = []
    strong_link = _feedback_value(feedback, "any_strong_confirmed_fraud") > 0.0
    fraud_channels = int(round(_feedback_value(feedback, "confirmed_fraud_channels")))
    max_rate = _feedback_value(feedback, "max_confirmed_fraud_rate")
    support_log = _feedback_value(feedback, "feedback_total_support_log")
    recent_profile = _feedback_value(feedback, "log_profile_confirmed_fraud_30d")
    profile_has_fraud = _feedback_value(feedback, "profile_has_confirmed_fraud") > 0.0
    receiver_has_fraud = _feedback_value(feedback, "receiver_has_confirmed_fraud") > 0.0
    device_has_fraud = _feedback_value(feedback, "device_has_confirmed_fraud") > 0.0

    if strong_link:
        items.append(
            EvidenceItem(
                code="STRONG_FRAUD_LINK",
                level="high",
                message="A strong device/receiver relationship view has matured confirmed-fraud history.",
            )
        )

    if fraud_channels >= 2:
        items.append(
            EvidenceItem(
                code="CORROBORATING_FRAUD_CHANNELS",
                level="high",
                message=f"Matured confirmed-fraud evidence appears across {fraud_channels} relationship channels.",
            )
        )
    elif fraud_channels == 1:
        items.append(
            EvidenceItem(
                code="SINGLE_FRAUD_CHANNEL",
                level="medium",
                message="One historical relationship channel contains matured confirmed-fraud evidence.",
            )
        )

    if recent_profile > 0.0:
        items.append(
            EvidenceItem(
                code="RECENT_PROFILE_FRAUD",
                level="high",
                message="The payment-profile context has matured confirmed-fraud activity within the trailing 30-day memory window.",
            )
        )
    elif profile_has_fraud:
        items.append(
            EvidenceItem(
                code="PROFILE_FRAUD_HISTORY",
                level="medium",
                message="The payment-profile context has historical matured confirmed-fraud evidence.",
            )
        )

    if receiver_has_fraud and not strong_link:
        items.append(
            EvidenceItem(
                code="RECEIVER_FRAUD_HISTORY",
                level="medium",
                message="The receiver relationship view has historical matured confirmed-fraud evidence.",
            )
        )
    if device_has_fraud and not strong_link:
        items.append(
            EvidenceItem(
                code="DEVICE_FRAUD_HISTORY",
                level="medium",
                message="The device relationship view has historical matured confirmed-fraud evidence.",
            )
        )

    total_support = max(int(round(math.expm1(max(support_log, 0.0)))), 0)
    if max_rate >= 0.25 and total_support >= 3:
        items.append(
            EvidenceItem(
                code="ELEVATED_HISTORICAL_FRAUD_RATE",
                level="medium",
                message=f"The strongest linked channel has a {max_rate:.0%} historical confirmed-fraud rate across matured feedback support.",
            )
        )

    delta = final - baseline
    if delta >= 0.05:
        items.append(
            EvidenceItem(
                code="RELATIONSHIP_RISK_UPLIFT",
                level="medium",
                message=f"Relationship memory raised the risk score by {delta:.3f} relative to the transaction-only baseline.",
            )
        )
    elif delta <= -0.05:
        items.append(
            EvidenceItem(
                code="RELATIONSHIP_RISK_REDUCTION",
                level="info",
                message=f"Relationship memory lowered the risk score by {abs(delta):.3f} relative to the transaction-only baseline.",
            )
        )

    if not items:
        items.append(
            EvidenceItem(
                code="CONTEXTUAL_FEEDBACK",
                level="info",
                message="Matured relationship history is available, but no single high-strength evidence rule fired.",
            )
        )

    return tuple(items[:5])


def score_transaction(
    *,
    baseline_risk: float,
    specialist_risk: float | None,
    graph_confidence: float,
    feedback: Mapping[str, Any] | None = None,
    transaction_id: str | int | None = None,
) -> RiskDecision:
    """Return the frozen LinkRisk v0.5 product-facing decision contract."""
    final_risk = champion_gate(baseline_risk, specialist_risk, graph_confidence)
    action = decide_action(final_risk, graph_confidence, feedback)
    evidence = build_evidence(baseline_risk, final_risk, graph_confidence, feedback)
    model_path = "baseline_fallback" if float(graph_confidence) == 0.0 else "feedback_specialist_v0.5"

    return RiskDecision(
        transaction_id=transaction_id,
        champion_version=CHAMPION_VERSION,
        baseline_risk=float(baseline_risk),
        specialist_risk=None if specialist_risk is None else float(specialist_risk),
        linkrisk_risk=final_risk,
        graph_confidence=float(graph_confidence),
        action=action,
        model_path=model_path,
        evidence=evidence,
    )
