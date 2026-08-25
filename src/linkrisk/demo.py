from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import plotly.graph_objects as go

from linkrisk.decision import RiskDecision, score_transaction


@dataclass(frozen=True)
class DemoScenario:
    key: str
    title: str
    subtitle: str
    baseline_risk: float
    specialist_risk: float | None
    graph_confidence: float
    feedback: dict[str, float]
    graph_kind: str
    takeaway: str


def demo_scenarios() -> list[DemoScenario]:
    return [
        DemoScenario(
            key="cold_start",
            title="Cold start — no relationship history",
            subtitle="The graph has nothing trustworthy to add, so LinkRisk falls back exactly to transaction ML.",
            baseline_risk=0.27,
            specialist_risk=None,
            graph_confidence=0.0,
            feedback={},
            graph_kind="cold_start",
            takeaway="No graph evidence is not treated as safety. The baseline score is preserved exactly.",
        ),
        DemoScenario(
            key="benign_shared",
            title="Benign shared context",
            subtitle="Several legitimate transactions share context, but there is no matured confirmed-fraud evidence.",
            baseline_risk=0.22,
            specialist_risk=0.30,
            graph_confidence=0.35,
            feedback={
                "confirmed_fraud_channels": 0.0,
                "feedback_total_support_log": math.log1p(18),
            },
            graph_kind="benign_shared",
            takeaway="Shared context alone does not equal fraud. LinkRisk stays out of the way when fraud evidence is absent.",
        ),
        DemoScenario(
            key="score_verify",
            title="Intermediate risk — score-band VERIFY",
            subtitle="Relationship history nudges a borderline payment into a lower-friction verification step.",
            baseline_risk=0.74,
            specialist_risk=0.82,
            graph_confidence=0.70,
            feedback={
                "confirmed_fraud_channels": 0.0,
                "feedback_total_support_log": math.log1p(11),
            },
            graph_kind="contextual",
            takeaway="Intermediate risk does not jump straight to hard review; the policy routes it to VERIFY.",
        ),
        DemoScenario(
            key="strong_verify",
            title="Strong fraud link — VERIFY override",
            subtitle="A strong matured fraud relationship exists, but the final score is still below REVIEW.",
            baseline_risk=0.45,
            specialist_risk=0.72,
            graph_confidence=0.65,
            feedback={
                "any_strong_confirmed_fraud": 1.0,
                "confirmed_fraud_channels": 1.0,
                "device_has_confirmed_fraud": 1.0,
                "max_confirmed_fraud_rate": 0.50,
                "feedback_total_support_log": math.log1p(6),
            },
            graph_kind="strong_link",
            takeaway="Strong evidence may force VERIFY, but relationship evidence alone is never allowed to force REVIEW.",
        ),
        DemoScenario(
            key="coordinated_review",
            title="Coordinated fraud signal — REVIEW",
            subtitle="Multiple matured fraud-linked relationship channels combine with elevated model risk.",
            baseline_risk=0.66,
            specialist_risk=0.94,
            graph_confidence=0.85,
            feedback={
                "any_strong_confirmed_fraud": 1.0,
                "confirmed_fraud_channels": 3.0,
                "profile_has_confirmed_fraud": 1.0,
                "device_has_confirmed_fraud": 1.0,
                "receiver_has_confirmed_fraud": 1.0,
                "log_profile_confirmed_fraud_30d": math.log1p(2),
                "max_confirmed_fraud_rate": 0.60,
                "feedback_total_support_log": math.log1p(10),
            },
            graph_kind="coordinated",
            takeaway="This is the core LinkRisk case: individually moderate transaction risk becomes high when corroborating, matured relationship evidence is trustworthy.",
        ),
        DemoScenario(
            key="ml_high_risk",
            title="High ML risk — graph unavailable",
            subtitle="The transaction model is already highly suspicious even though relationship evidence is missing.",
            baseline_risk=0.91,
            specialist_risk=None,
            graph_confidence=0.0,
            feedback={},
            graph_kind="cold_start",
            takeaway="Missing graph evidence cannot suppress a strong transaction-level warning. The baseline still triggers REVIEW.",
        ),
    ]


def evaluate_scenario(scenario: DemoScenario, transaction_id: str = "DEMO-TX") -> RiskDecision:
    return score_transaction(
        baseline_risk=scenario.baseline_risk,
        specialist_risk=scenario.specialist_risk,
        graph_confidence=scenario.graph_confidence,
        feedback=scenario.feedback,
        transaction_id=transaction_id,
    )


def relationship_figure(graph_kind: str) -> go.Figure:
    layouts: dict[str, tuple[list[tuple[str, float, float, str]], list[tuple[int, int]]]] = {
        "cold_start": (
            [("Current transaction", 0.0, 0.0, "current")],
            [],
        ),
        "benign_shared": (
            [
                ("Current transaction", 1.0, 0.0, "current"),
                ("Shared context", 0.0, 0.0, "context"),
                ("Prior legitimate A", -1.0, 0.7, "legit"),
                ("Prior legitimate B", -1.0, -0.7, "legit"),
            ],
            [(0, 1), (1, 2), (1, 3)],
        ),
        "contextual": (
            [
                ("Current transaction", 1.0, 0.0, "current"),
                ("Matured context", 0.0, 0.0, "context"),
                ("Prior transaction", -1.0, 0.0, "legit"),
            ],
            [(0, 1), (1, 2)],
        ),
        "strong_link": (
            [
                ("Current transaction", 1.0, 0.0, "current"),
                ("Strong relationship", 0.0, 0.0, "context"),
                ("Confirmed fraud", -1.0, 0.0, "fraud"),
            ],
            [(0, 1), (1, 2)],
        ),
        "coordinated": (
            [
                ("Current transaction", 1.2, 0.0, "current"),
                ("Payment profile", 0.2, 0.8, "context"),
                ("Device context", 0.2, 0.0, "context"),
                ("Receiver context", 0.2, -0.8, "context"),
                ("Confirmed fraud A", -1.0, 0.8, "fraud"),
                ("Confirmed fraud B", -1.0, 0.0, "fraud"),
                ("Confirmed fraud C", -1.0, -0.8, "fraud"),
            ],
            [(0, 1), (0, 2), (0, 3), (1, 4), (2, 5), (3, 6)],
        ),
    }

    nodes, edges = layouts.get(graph_kind, layouts["contextual"])
    palette = {
        "current": "#6EE7F9",
        "context": "#A78BFA",
        "fraud": "#FB7185",
        "legit": "#94A3B8",
    }

    fig = go.Figure()
    for left, right in edges:
        x0, y0 = nodes[left][1], nodes[left][2]
        x1, y1 = nodes[right][1], nodes[right][2]
        fig.add_trace(
            go.Scatter(
                x=[x0, x1],
                y=[y0, y1],
                mode="lines",
                line=dict(color="rgba(148,163,184,0.40)", width=2),
                hoverinfo="skip",
                showlegend=False,
            )
        )

    for label, x, y, node_type in nodes:
        fig.add_trace(
            go.Scatter(
                x=[x],
                y=[y],
                mode="markers+text",
                text=[label],
                textposition="bottom center",
                marker=dict(size=28, color=palette[node_type], line=dict(width=2, color="#0F172A")),
                hovertemplate=f"{label}<extra></extra>",
                showlegend=False,
            )
        )

    fig.update_layout(
        height=330,
        margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(visible=False, range=[-1.6, 1.7]),
        yaxis=dict(visible=False, range=[-1.3, 1.3]),
        font=dict(color="#E2E8F0"),
    )
    return fig
