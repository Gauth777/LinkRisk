from __future__ import annotations

import json
import math
from pathlib import Path
import sys

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from linkrisk.decision import (
    REVIEW_THRESHOLD,
    VERIFY_THRESHOLD,
    score_transaction,
)
from linkrisk.demo import demo_scenarios, evaluate_scenario, relationship_figure


st.set_page_config(
    page_title="LinkRisk | AI Risk Intelligence",
    page_icon="LR",
    layout="wide",
)

st.markdown(
    """
    <style>
    .stApp { background: #07111f; color: #e5edf7; }
    [data-testid="stSidebar"] { background: #0b1728; }
    .block-container { padding-top: 1.5rem; max-width: 1500px; }
    .eyebrow { color:#7dd3fc; font-size:.78rem; letter-spacing:.14em; text-transform:uppercase; font-weight:700; }
    .hero-title { font-size:2.45rem; font-weight:800; line-height:1.05; margin:.25rem 0 .45rem; }
    .hero-sub { color:#9fb0c5; font-size:1.03rem; max-width:850px; }
    .decision { border-radius:18px; padding:1rem 1.2rem; font-weight:800; font-size:1.35rem; text-align:center; letter-spacing:.08em; }
    .ALLOW { background:#0f2f27; color:#86efac; border:1px solid #1f6a50; }
    .VERIFY { background:#33280e; color:#fde68a; border:1px solid #806414; }
    .REVIEW { background:#3a1620; color:#fda4af; border:1px solid #8b2c43; }
    .evidence-high { border-left:3px solid #fb7185; padding:.5rem .75rem; margin:.55rem 0; background:#1e1722; border-radius:0 10px 10px 0; }
    .evidence-medium { border-left:3px solid #fbbf24; padding:.5rem .75rem; margin:.55rem 0; background:#211d14; border-radius:0 10px 10px 0; }
    .evidence-info { border-left:3px solid #38bdf8; padding:.5rem .75rem; margin:.55rem 0; background:#101d2b; border-radius:0 10px 10px 0; }
    .score-label { color:#9fb0c5; font-size:.82rem; margin-bottom:.15rem; }
    .score-value { font-size:1.75rem; font-weight:800; }
    div[data-testid="stMetric"] { background:#0d1b2e; border:1px solid #1d3048; padding:.75rem; border-radius:14px; }
    </style>
    """,
    unsafe_allow_html=True,
)


def load_policy_snapshot() -> dict | None:
    path = ROOT / "artifacts" / "results" / "policy_impact_validation.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def pct(value: float) -> str:
    return f"{100 * float(value):.2f}%"


def render_score(label: str, value: float | None) -> None:
    if value is None:
        st.markdown(f'<div class="score-label">{label}</div><div class="score-value">N/A</div>', unsafe_allow_html=True)
        return
    st.markdown(
        f'<div class="score-label">{label}</div><div class="score-value">{value:.3f}</div>',
        unsafe_allow_html=True,
    )
    st.progress(min(max(float(value), 0.0), 1.0))


def render_decision(decision, graph_kind: str, takeaway: str) -> None:
    score_cols = st.columns(4)
    with score_cols[0]:
        render_score("Transaction ML risk", decision.baseline_risk)
    with score_cols[1]:
        render_score("Relationship specialist", decision.specialist_risk)
    with score_cols[2]:
        render_score("Graph confidence", decision.graph_confidence)
    with score_cols[3]:
        render_score("Final LinkRisk risk", decision.linkrisk_risk)

    left, right = st.columns([0.92, 1.08], gap="large")
    with left:
        st.markdown("### Decision")
        st.markdown(
            f'<div class="decision {decision.action.value}">{decision.action.value}</div>',
            unsafe_allow_html=True,
        )
        st.caption(
            f"Model path: `{decision.model_path}` · VERIFY ≥ {VERIFY_THRESHOLD:.3f} · REVIEW ≥ {REVIEW_THRESHOLD:.3f}"
        )

        st.markdown("### Why LinkRisk decided this")
        for item in decision.evidence:
            level = item.level if item.level in {"high", "medium", "info"} else "info"
            st.markdown(
                f'<div class="evidence-{level}"><strong>{item.code}</strong><br>{item.message}</div>',
                unsafe_allow_html=True,
            )

        st.info(takeaway)

    with right:
        st.markdown("### Local relationship view")
        st.plotly_chart(relationship_figure(graph_kind), use_container_width=True, config={"displayModeBar": False})
        st.caption(
            "This visualization is explanatory. LinkRisk uses causal streaming relationship histories rather than a GNN or a global graph database."
        )


def render_validation_snapshot(snapshot: dict | None) -> None:
    st.markdown("### Frozen validation snapshot")
    if not snapshot:
        st.warning(
            "Local policy validation artifact not found. Run `python scripts/evaluate_policy_impact.py` to populate real validation metrics."
        )
        return

    review = snapshot.get("review_metrics", {})
    actions = {row["action"]: row for row in snapshot.get("actions", [])}

    metrics = st.columns(4)
    metrics[0].metric("REVIEW precision", pct(review.get("precision", 0.0)))
    metrics[1].metric("REVIEW recall", pct(review.get("recall", 0.0)))
    metrics[2].metric("PR-AUC", f"{review.get('pr_auc', 0.0):.4f}")
    metrics[3].metric("REVIEW FPR", pct(review.get("false_positive_rate", 0.0)))

    action_cols = st.columns(3)
    for col, name in zip(action_cols, ["ALLOW", "VERIFY", "REVIEW"]):
        row = actions.get(name, {})
        col.metric(name, pct(row.get("row_share", 0.0)), f"fraud rate {pct(row.get('fraud_rate', 0.0))}")

    st.caption("Development validation only. The held-out chronological test period remains sealed.")


st.markdown('<div class="eyebrow">Razorpay AI Buildathon · Track 2</div>', unsafe_allow_html=True)
st.markdown('<div class="hero-title">LinkRisk</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="hero-sub">Confidence-aware payment risk intelligence that turns delayed fraud confirmations into relationship memory — and falls back safely to transaction ML when that evidence is weak.</div>',
    unsafe_allow_html=True,
)

snapshot = load_policy_snapshot()
render_validation_snapshot(snapshot)
st.divider()

scenarios = demo_scenarios()
scenario_by_title = {scenario.title: scenario for scenario in scenarios}

with st.sidebar:
    st.markdown("## Demo controls")
    mode = st.radio("Mode", ["Guided scenarios", "Policy sandbox"], index=0)
    st.caption("Guided scenarios are illustrative inputs passed through the real frozen decision policy. They are not claimed as held-out dataset examples.")

if mode == "Guided scenarios":
    selected_title = st.sidebar.selectbox("Choose a story", list(scenario_by_title), index=4)
    scenario = scenario_by_title[selected_title]

    st.markdown(f"## {scenario.title}")
    st.write(scenario.subtitle)
    render_decision(evaluate_scenario(scenario), scenario.graph_kind, scenario.takeaway)

else:
    st.markdown("## Policy sandbox")
    st.write("Change the evidence and see how the frozen LinkRisk decision contract behaves. This is a policy simulator, not model retraining.")

    control_a, control_b, control_c = st.columns(3)
    with control_a:
        baseline = st.slider("Transaction ML risk", 0.0, 1.0, 0.45, 0.01)
    with control_b:
        specialist = st.slider("Relationship specialist risk", 0.0, 1.0, 0.72, 0.01)
    with control_c:
        confidence = st.slider("Graph confidence", 0.0, 1.0, 0.65, 0.01)

    evidence_a, evidence_b, evidence_c = st.columns(3)
    with evidence_a:
        strong_link = st.checkbox("Strong matured fraud link", value=True)
    with evidence_b:
        channels = st.slider("Confirmed-fraud channels", 0, 4, 1)
    with evidence_c:
        recent_profile = st.checkbox("Recent profile fraud memory", value=False)

    feedback = {
        "any_strong_confirmed_fraud": float(strong_link),
        "confirmed_fraud_channels": float(channels),
        "profile_has_confirmed_fraud": float(channels > 0),
        "device_has_confirmed_fraud": float(strong_link),
        "log_profile_confirmed_fraud_30d": math.log1p(1) if recent_profile else 0.0,
        "max_confirmed_fraud_rate": 0.50 if channels > 0 else 0.0,
        "feedback_total_support_log": math.log1p(6) if channels > 0 else math.log1p(12),
    }

    specialist_input = specialist if confidence > 0 else None
    decision = score_transaction(
        baseline_risk=baseline,
        specialist_risk=specialist_input,
        graph_confidence=confidence,
        feedback=feedback,
        transaction_id="SANDBOX-TX",
    )

    if confidence == 0:
        graph_kind = "cold_start"
    elif channels >= 2:
        graph_kind = "coordinated"
    elif strong_link:
        graph_kind = "strong_link"
    else:
        graph_kind = "contextual"

    render_decision(
        decision,
        graph_kind,
        "The sandbox uses the same frozen gate, thresholds and evidence rules as the runtime decision contract.",
    )

st.divider()
with st.expander("How the final system works"):
    st.markdown(
        """
        **1. Transaction ML** scores the current payment using the frozen XGBoost baseline.  
        **2. Relationship memory** summarizes strictly prior, matured historical evidence.  
        **3. The v0.5 specialist** scores transaction + relationship + delayed-feedback features.  
        **4. Confidence gating** controls how strongly the specialist can move the baseline score.  
        **5. Policy** maps the final risk to ALLOW, VERIFY or REVIEW.  
        **6. Deterministic evidence** explains the decision without putting an LLM in the decision path.

        Scores are **risk/ranking scores, not calibrated fraud probabilities**. Confirmed-fraud feedback uses a **simulated fixed 72-hour adjudication delay** in the development experiment.
        """
    )
