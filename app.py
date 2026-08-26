from __future__ import annotations

import json
from pathlib import Path
import sys

import networkx as nx
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from linkrisk.engine import FrozenChampionScorer
from linkrisk.live_engine import (
    LABEL_DELAY_SECONDS,
    LiveLinkRiskEngine,
    LiveTransactionInput,
    format_sim_time,
)
from linkrisk.mentalist_runtime_policy import FrozenMentalistScorer


APP_RUNTIME_VERSION = "mentalist-live-v1"

st.set_page_config(
    page_title="LinkRisk | Mentalist Risk Engine",
    page_icon="🔗",
    layout="wide",
)

st.markdown(
    """
    <style>
    .stApp { background:#07111f; color:#e5edf7; }
    [data-testid="stSidebar"] { background:#0b1728; }
    .block-container { padding-top:1.35rem; max-width:1500px; }
    .eyebrow { color:#7dd3fc; font-size:.76rem; letter-spacing:.14em; text-transform:uppercase; font-weight:800; }
    .hero { font-size:2.4rem; line-height:1.05; font-weight:850; margin:.2rem 0 .35rem; }
    .sub { color:#9fb0c5; max-width:980px; font-size:1rem; margin-bottom:1.15rem; }
    .decision { border-radius:14px; padding:.88rem 1rem; text-align:center; font-size:1.2rem; font-weight:850; letter-spacing:.09em; }
    .ALLOW { background:#0f2f27; color:#86efac; border:1px solid #1f6a50; }
    .VERIFY { background:#33280e; color:#fde68a; border:1px solid #806414; }
    .REVIEW { background:#3a1620; color:#fda4af; border:1px solid #8b2c43; }
    .case { background:#0d1b2e; border:1px solid #1d3048; border-radius:14px; padding:.85rem 1rem; margin:.5rem 0; }
    .clue-on { color:#fde68a; font-weight:750; }
    .clue-off { color:#718096; }
    .evidence-high { border-left:3px solid #fb7185; padding:.55rem .75rem; margin:.55rem 0; background:#1e1722; border-radius:0 10px 10px 0; }
    .evidence-medium { border-left:3px solid #fbbf24; padding:.55rem .75rem; margin:.55rem 0; background:#211d14; border-radius:0 10px 10px 0; }
    .evidence-info { border-left:3px solid #38bdf8; padding:.55rem .75rem; margin:.55rem 0; background:#101d2b; border-radius:0 10px 10px 0; }
    .live-dot { display:inline-block; width:9px; height:9px; background:#4ade80; border-radius:50%; margin-right:.4rem; box-shadow:0 0 12px #4ade80; }
    div[data-testid="stMetric"] { background:#0d1b2e; border:1px solid #1d3048; padding:.72rem; border-radius:14px; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource(show_spinner=False)
def load_models() -> tuple[FrozenChampionScorer, FrozenMentalistScorer]:
    return (
        FrozenChampionScorer.from_artifacts(ROOT),
        FrozenMentalistScorer.from_artifacts(ROOT),
    )


def _load_json(name: str) -> dict | None:
    path = ROOT / "artifacts" / "results" / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def relationship_network_figure(network: dict) -> go.Figure:
    graph = nx.Graph()
    node_meta = {node["id"]: node for node in network.get("nodes", [])}
    for node_id, meta in node_meta.items():
        graph.add_node(node_id, **meta)
    for edge in network.get("edges", []):
        graph.add_edge(edge["source"], edge["target"])

    if len(graph) == 1:
        only = next(iter(graph.nodes))
        positions = {only: (0.0, 0.0)}
    elif len(graph) > 1:
        positions = nx.spring_layout(graph, seed=17, k=1.35)
    else:
        positions = {}

    figure = go.Figure()
    for source, target in graph.edges:
        x0, y0 = positions[source]
        x1, y1 = positions[target]
        figure.add_trace(
            go.Scatter(
                x=[x0, x1], y=[y0, y1], mode="lines",
                line=dict(color="rgba(148,163,184,.35)", width=2),
                hoverinfo="skip", showlegend=False,
            )
        )

    palette = {
        "current": "#67e8f9",
        "relation": "#a78bfa",
        "fraud": "#fb7185",
        "legitimate": "#4ade80",
        "pending": "#fbbf24",
        "prior": "#94a3b8",
    }
    sizes = {"current": 33, "relation": 25, "fraud": 28, "legitimate": 25, "pending": 25, "prior": 23}

    for kind, color in palette.items():
        ids = [node_id for node_id, meta in node_meta.items() if meta["kind"] == kind]
        if not ids:
            continue
        figure.add_trace(
            go.Scatter(
                x=[positions[node_id][0] for node_id in ids],
                y=[positions[node_id][1] for node_id in ids],
                mode="markers+text",
                text=[node_meta[node_id]["label"] for node_id in ids],
                textposition="bottom center",
                marker=dict(size=[sizes[kind]] * len(ids), color=color, line=dict(width=2, color="#07111f")),
                customdata=[node_meta[node_id]["detail"] for node_id in ids],
                hovertemplate="%{text}<br>%{customdata}<extra></extra>",
                showlegend=False,
            )
        )

    figure.update_layout(
        height=430,
        margin=dict(l=5, r=5, t=5, b=5),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        font=dict(color="#e2e8f0"),
    )
    return figure


def render_decision(record: dict) -> None:
    decision = record["decision"]
    mentalist = record.get("mentalist") or {}
    cols = st.columns(5)
    cols[0].metric("Transaction risk", f"{decision['baseline_risk']:.3f}")
    cols[1].metric("v0.5 risk", f"{decision['linkrisk_risk']:.3f}")
    cols[2].metric("Jane score", f"{mentalist.get('score', 0.0):.3f}")
    cols[3].metric("Independent clues", str(mentalist.get("clue_count", 0)))
    cols[4].metric("Trusted confidence", f"{decision['graph_confidence']:.3f}")

    v5_action = decision.get("v5_action", decision["action"])
    final_action = decision["action"]
    transition = final_action if v5_action == final_action else f"{v5_action} → {final_action}"
    st.markdown(
        f'<div class="decision {final_action}">{transition}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Jane does not modify the v0.5 risk score. The frozen Mentalist policy only reallocates action routing from causal proactive evidence."
    )


def render_mentalist_case(record: dict) -> None:
    case = record["case_file"]
    mentalist = case.get("mentalist")
    st.subheader("Patrick Jane — case file")
    if mentalist is None:
        st.info("Mentalist is not enabled for this runtime record.")
        return

    active = mentalist["clue_families"]
    labels = {
        "velocity": "Velocity / burst",
        "behavior_change": "Behavior change",
        "coordination": "Network coordination",
        "reuse_churn": "Reuse / churn",
    }
    for key, label in labels.items():
        css = "clue-on" if active.get(key, False) else "clue-off"
        marker = "ACTIVE" if active.get(key, False) else "quiet"
        st.markdown(f'<div class="{css}">{label}: {marker}</div>', unsafe_allow_html=True)

    st.markdown(
        f"""
        <div class="case">
        <b>Mentalist score:</b> {mentalist['score']:.4f} &nbsp;|&nbsp;
        <b>Frozen boundary:</b> {mentalist['score_threshold']:.4f}<br>
        <b>Independent evidence families:</b> {mentalist['clue_count']} / 4 &nbsp;|&nbsp;
        <b>Minimum required:</b> {mentalist['min_clue_families']}<br>
        <b>Routing reason:</b> {case['routing_reason']}<br>
        {case['explanation']}
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("#### Trusted history — separate evidence channel")
    history_cols = st.columns(3)
    history_cols[0].metric("History channels", case["trusted_history_channels"])
    history_cols[1].metric("Fraud channels", case["trusted_fraud_channels"])
    history_cols[2].metric(
        "Confirmed fraud evidence",
        "Present" if case["trusted_fraud_evidence_present"] else "None",
    )
    if mentalist.get("promoted_by_jane") and not case["trusted_fraud_evidence_present"]:
        st.success("Proactive VERIFY formed without any matured confirmed-fraud relationship.")
    st.caption("Mentalist's proactive model never consumes confirmed-fraud history as an input.")


def render_v5_evidence(record: dict) -> None:
    st.markdown("#### v0.5 trusted-memory evidence")
    for item in record["decision"]["evidence"]:
        level = item.get("level", "info")
        st.markdown(
            f'<div class="evidence-{level}"><b>{item["code"]}</b><br>{item["message"]}</div>',
            unsafe_allow_html=True,
        )


def render_performance() -> None:
    runtime = _load_json("mentalist_runtime_validation.json")
    st.subheader("Frozen development/validation evidence")
    st.caption("The chronological held-out test remains sealed. These are development validation metrics only.")
    if runtime is None:
        st.info("Run scripts/validate_mentalist_runtime_policy.py locally to populate the runtime validation snapshot.")
        return

    stable = runtime.get("stable_v5", {})
    final = runtime.get("fixed_runtime", {})
    cols = st.columns(4)
    cols[0].metric("v0.5 fraud capture", f"{100 * stable.get('fraud_capture', 0):.2f}%")
    cols[1].metric("Mentalist fraud capture", f"{100 * final.get('fraud_capture', 0):.2f}%")
    cols[2].metric("v0.5 legit friction", f"{100 * stable.get('legitimate_friction', 0):.2f}%")
    cols[3].metric("Mentalist legit friction", f"{100 * final.get('legitimate_friction', 0):.2f}%")
    st.markdown(
        f"**Runtime reproduction:** {100 * runtime.get('action_agreement', 0):.6f}% action agreement, "
        f"{runtime.get('action_mismatch_count', 0)} mismatches."
    )
    gate = runtime.get("gate", {})
    if gate.get("pass"):
        st.success("Runtime freeze gate passed: exact v1.0 reproduction, immutable REVIEW, same validation capacity.")
    else:
        st.error("Runtime freeze gate has not passed. Do not open the held-out test.")


st.markdown('<div class="eyebrow"><span class="live-dot"></span>Mentalist live risk operations</div>', unsafe_allow_html=True)
st.markdown('<div class="hero">LinkRisk</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub">A proactive payment-risk investigator: transaction intelligence, causal behavioral deduction, relationship evidence, and delayed trusted feedback remain separate until the frozen action router decides what deserves intervention.</div>',
    unsafe_allow_html=True,
)

try:
    champion, mentalist = load_models()
except Exception as exc:
    st.error(
        "The frozen runtime artifacts could not be loaded. Ensure the v0.5 models, mentalist_v7_candidate.joblib, "
        "mentalist_v7_validation.json, and mentalist_runtime_policy.json exist locally. Run the runtime freeze scripts first."
    )
    st.exception(exc)
    st.stop()

if st.session_state.get("live_engine_version") != APP_RUNTIME_VERSION:
    st.session_state.live_engine = LiveLinkRiskEngine(champion, mentalist_scorer=mentalist)
    st.session_state.live_engine_version = APP_RUNTIME_VERSION
    st.session_state.selected_transaction = None

engine: LiveLinkRiskEngine = st.session_state.live_engine

with st.sidebar:
    st.markdown("### Simulation clock")
    st.markdown(f"**{format_sim_time(engine.clock)}**")
    st.caption("An adjudicated outcome becomes usable only at max(original transaction + 72h, actual adjudication time).")
    c1, c2 = st.columns(2)
    if c1.button("+1 hour", use_container_width=True):
        engine.advance_time(60 * 60)
        st.rerun()
    if c2.button("+24 hours", use_container_width=True):
        engine.advance_time(24 * 60 * 60)
        st.rerun()
    if st.button("+72 hours", use_container_width=True):
        engine.advance_time(LABEL_DELAY_SECONDS)
        st.rerun()
    st.divider()
    auto_advance = st.checkbox("Auto-advance 5 min after scoring", value=True)
    if st.button("Reset live session", use_container_width=True):
        engine.reset()
        st.session_state.selected_transaction = None
        st.rerun()

live_tab, performance_tab = st.tabs(["Mentalist Live Engine", "Validation Evidence"])

with live_tab:
    st.markdown("### 1 · Submit an incoming payment")
    st.caption("Repeated identifiers create causal session relationships. The adapter is IEEE-CIS-compatible; it does not claim masked fields are literal real-world identities.")

    with st.form("payment_form", clear_on_submit=False):
        top = st.columns(3)
        amount = top[0].number_input("Amount", min_value=0.0, value=2500.0, step=100.0)
        payment_profile = top[1].text_input("Payment profile", value="PROFILE-A")
        device_info = top[2].text_input("Device signature", value="Windows")
        bottom = st.columns(3)
        receiver_domain = bottom[0].text_input("Receiver email-domain context", value="gmail.com")
        browser_context = bottom[1].text_input("Browser/device context", value="chrome 63.0")
        product_code = bottom[2].selectbox("Product code", ["W", "C", "H", "R", "S"], index=0)
        with st.expander("Additional transaction attributes"):
            a1, a2, a3, a4 = st.columns(4)
            payer_domain = a1.text_input("Payer email domain", value="gmail.com")
            device_type = a2.selectbox("Device type", ["desktop", "mobile"], index=0)
            card_network = a3.selectbox("Card network", ["visa", "mastercard", "american express", "discover"], index=0)
            card_type = a4.selectbox("Card type", ["debit", "credit"], index=0)
        submitted = st.form_submit_button("Investigate payment", type="primary", use_container_width=True)

    if submitted:
        event = LiveTransactionInput(
            amount=amount,
            payment_profile=payment_profile,
            device_info=device_info,
            receiver_domain=receiver_domain,
            browser_context=browser_context,
            product_code=product_code,
            payer_domain=payer_domain,
            device_type=device_type,
            card_network=card_network,
            card_type=card_type,
        )
        try:
            record = engine.score_event(event)
            st.session_state.selected_transaction = record["transaction_id"]
            if auto_advance:
                engine.advance_time(5 * 60)
            st.rerun()
        except Exception as exc:
            st.exception(exc)

    st.divider()
    st.markdown("### 2 · Live transaction feed")
    feed = engine.feed()
    if feed.empty:
        st.info("No payments yet. Submit transactions with changing or reused profiles/devices/contexts to let Jane build a causal case from prior activity.")
    else:
        st.dataframe(feed.iloc[::-1], use_container_width=True, hide_index=True)
        transaction_ids = engine.transaction_ids
        default_id = st.session_state.selected_transaction or transaction_ids[-1]
        default_index = transaction_ids.index(default_id) if default_id in transaction_ids else len(transaction_ids) - 1
        selected = st.selectbox("Investigate transaction", transaction_ids, index=default_index)
        st.session_state.selected_transaction = selected
        record = engine.get_record(selected)

        st.divider()
        st.markdown(f"### 3 · Transaction investigator — {selected}")
        render_decision(record)
        left, right = st.columns([1.05, 1.25])

        with left:
            render_mentalist_case(record)
            render_v5_evidence(record)
            st.markdown("#### Adjudication / feedback")
            status = record["adjudication"]
            if status["state"] == "unadjudicated":
                st.caption("No confirmed outcome is known. This transaction cannot influence trusted fraud memory.")
            elif status["state"] == "pending":
                hours = status["seconds_remaining"] / 3600.0
                st.warning(f"{status['outcome'].title()} recorded; usable in {hours:.1f} hours.")
            else:
                st.success(f"{status['outcome'].title()} is matured and eligible for future trusted memory.")

            b1, b2, b3 = st.columns(3)
            if b1.button("Confirm fraud", key=f"fraud-{selected}", use_container_width=True):
                engine.adjudicate(selected, "fraud")
                st.rerun()
            if b2.button("Confirm legitimate", key=f"legit-{selected}", use_container_width=True):
                engine.adjudicate(selected, "legitimate")
                st.rerun()
            if b3.button("Clear", key=f"clear-{selected}", use_container_width=True):
                engine.clear_adjudication(selected)
                st.rerun()

        with right:
            st.markdown("#### Relationship neighborhood at decision time")
            network = record["network"]
            if not network.get("edges"):
                st.caption("No strictly earlier session transaction shared a validated relationship key. Same-timestamp rows cannot see one another.")
            st.plotly_chart(relationship_network_figure(network), use_container_width=True, config={"displayModeBar": False})
            st.caption("Cyan=current · purple=relationship · red=matured fraud · green=matured legitimate · amber=recorded/pending · gray=prior/unadjudicated.")

        with st.expander("Technical state"):
            proactive_nonzero = {k: v for k, v in record["proactive_features"].items() if abs(float(v)) > 1e-12}
            feedback_nonzero = {k: v for k, v in record["feedback_features"].items() if abs(float(v)) > 1e-12}
            t1, t2 = st.columns(2)
            with t1:
                st.markdown("**Proactive Mentalist features**")
                st.json(proactive_nonzero or {"state": "No proactive signal"})
            with t2:
                st.markdown("**Delayed trusted-memory features**")
                st.json(feedback_nonzero or {"state": "No matured feedback signal"})

    st.divider()
    st.markdown("#### Demo principle")
    st.markdown(
        "Build several strictly earlier transactions that reuse or rotate profile/device/browser context over short intervals. Jane can form a VERIFY case from corroborating current structure before any fraud is confirmed. Separately, adjudicate an older transaction and advance time to demonstrate how trusted history becomes an additional clue rather than automatic guilt."
    )

with performance_tab:
    render_performance()
