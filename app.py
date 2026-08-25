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


st.set_page_config(
    page_title="LinkRisk | Live Fraud Risk Engine",
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
    .sub { color:#9fb0c5; max-width:920px; font-size:1rem; margin-bottom:1.15rem; }
    .panel { background:#0d1b2e; border:1px solid #1d3048; border-radius:16px; padding:1rem 1.05rem; }
    .muted { color:#93a4b8; font-size:.87rem; }
    .live-dot { display:inline-block; width:9px; height:9px; background:#4ade80; border-radius:50%; margin-right:.4rem; box-shadow:0 0 12px #4ade80; }
    .decision { border-radius:14px; padding:.88rem 1rem; text-align:center; font-size:1.2rem; font-weight:850; letter-spacing:.09em; }
    .ALLOW { background:#0f2f27; color:#86efac; border:1px solid #1f6a50; }
    .VERIFY { background:#33280e; color:#fde68a; border:1px solid #806414; }
    .REVIEW { background:#3a1620; color:#fda4af; border:1px solid #8b2c43; }
    .evidence-high { border-left:3px solid #fb7185; padding:.55rem .75rem; margin:.55rem 0; background:#1e1722; border-radius:0 10px 10px 0; }
    .evidence-medium { border-left:3px solid #fbbf24; padding:.55rem .75rem; margin:.55rem 0; background:#211d14; border-radius:0 10px 10px 0; }
    .evidence-info { border-left:3px solid #38bdf8; padding:.55rem .75rem; margin:.55rem 0; background:#101d2b; border-radius:0 10px 10px 0; }
    div[data-testid="stMetric"] { background:#0d1b2e; border:1px solid #1d3048; padding:.72rem; border-radius:14px; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource(show_spinner=False)
def load_scorer() -> FrozenChampionScorer:
    return FrozenChampionScorer.from_artifacts(ROOT)


def load_policy_snapshot() -> dict | None:
    path = ROOT / "artifacts" / "results" / "policy_impact_validation.json"
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
                x=[x0, x1],
                y=[y0, y1],
                mode="lines",
                line=dict(color="rgba(148,163,184,.35)", width=2),
                hoverinfo="skip",
                showlegend=False,
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
    size = {
        "current": 33,
        "relation": 25,
        "fraud": 28,
        "legitimate": 25,
        "pending": 25,
        "prior": 23,
    }

    for kind in palette:
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
                marker=dict(
                    size=[size[kind]] * len(ids),
                    color=palette[kind],
                    line=dict(width=2, color="#07111f"),
                ),
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
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        font=dict(color="#e2e8f0"),
    )
    return figure


def render_decision(record: dict) -> None:
    decision = record["decision"]
    scores = st.columns(4)
    scores[0].metric("Transaction ML", f"{decision['baseline_risk']:.3f}")
    scores[1].metric("Relationship specialist", f"{decision['specialist_risk']:.3f}")
    scores[2].metric("Evidence confidence", f"{decision['graph_confidence']:.3f}")
    scores[3].metric("Final LinkRisk", f"{decision['linkrisk_risk']:.3f}")

    st.markdown(
        f'<div class="decision {decision["action"]}">{decision["action"]}</div>',
        unsafe_allow_html=True,
    )

    if decision["model_path"] == "baseline_fallback":
        st.caption("Relationship confidence is zero, so the final score is the transaction-only baseline exactly.")
    else:
        st.caption("The frozen v0.5 confidence gate blended transaction risk with delayed relationship evidence.")


def render_evidence(record: dict) -> None:
    st.subheader("Why LinkRisk made this decision")
    for item in record["decision"]["evidence"]:
        level = item.get("level", "info")
        st.markdown(
            f'<div class="evidence-{level}"><b>{item["code"]}</b><br>{item["message"]}</div>',
            unsafe_allow_html=True,
        )


def render_performance() -> None:
    snapshot = load_policy_snapshot()
    st.subheader("Frozen validation evidence")
    st.caption("This page reports the offline development/validation evidence supporting the live engine. It is not the engine itself.")
    if snapshot is None:
        st.info("Run scripts/evaluate_policy_impact.py locally to populate the frozen validation snapshot.")
        return

    metrics = snapshot.get("review_metrics", {})
    cols = st.columns(4)
    cols[0].metric("REVIEW precision", f"{100 * metrics.get('precision', 0):.2f}%")
    cols[1].metric("REVIEW recall", f"{100 * metrics.get('recall', 0):.2f}%")
    cols[2].metric("PR-AUC", f"{metrics.get('pr_auc', 0):.4f}")
    cols[3].metric("REVIEW FPR", f"{100 * metrics.get('false_positive_rate', 0):.2f}%")

    actions = snapshot.get("actions", [])
    if actions:
        st.markdown("#### Frozen policy distribution")
        st.dataframe(
            [
                {
                    "Action": row["action"],
                    "Traffic share": f"{100 * row['row_share']:.2f}%",
                    "Fraud rate": f"{100 * row['fraud_rate']:.2f}%",
                    "Rows": row["rows"],
                }
                for row in actions
            ],
            use_container_width=True,
            hide_index=True,
        )

    st.warning("Held-out test remains sealed. The live console does not access test labels.")


st.markdown('<div class="eyebrow"><span class="live-dot"></span>Live risk operations</div>', unsafe_allow_html=True)
st.markdown('<div class="hero">LinkRisk</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub">Submit payments, adjudicate outcomes, advance simulated time, and watch delayed fraud confirmations become relationship memory for future transactions.</div>',
    unsafe_allow_html=True,
)

try:
    scorer = load_scorer()
except Exception as exc:
    st.error(
        "The frozen model artifacts could not be loaded. Ensure baseline_preprocessor.joblib, "
        "baseline_xgboost.joblib, feedback_specialist_v5.joblib and baseline_features.json exist locally."
    )
    st.exception(exc)
    st.stop()

if "live_engine" not in st.session_state:
    st.session_state.live_engine = LiveLinkRiskEngine(scorer)
if "selected_transaction" not in st.session_state:
    st.session_state.selected_transaction = None

engine: LiveLinkRiskEngine = st.session_state.live_engine

with st.sidebar:
    st.markdown("### Simulation clock")
    st.markdown(f"**{format_sim_time(engine.clock)}**")
    st.caption("Fraud/legitimate adjudications can enter relationship memory only after the frozen 72-hour delay.")

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

    st.divider()
    st.caption("Use the same Profile, Device, Receiver domain or Browser values on later payments to create real session relationships. Unseen categorical values are handled by the frozen model adapter.")

live_tab, performance_tab = st.tabs(["Live Engine", "Performance & Validation"])

with live_tab:
    st.markdown("### 1 · Submit an incoming payment")
    st.caption("The form is a model-compatible runtime adapter. Repeated identifiers create the same relationship keys used by the validated LinkRisk pipeline.")

    with st.form("payment_form", clear_on_submit=False):
        top = st.columns(3)
        amount = top[0].number_input("Amount", min_value=0.0, value=2500.0, step=100.0)
        payment_profile = top[1].text_input("Payment profile", value="PROFILE-A", help="Stable demo fingerprint mapped into the masked card/address profile used by v0.5.")
        device_info = top[2].text_input("Device signature", value="Windows")

        bottom = st.columns(3)
        receiver_domain = bottom[0].text_input("Receiver email-domain context", value="gmail.com")
        browser_context = bottom[1].text_input("Browser/device context", value="chrome 63.0")
        product_code = bottom[2].selectbox("Product code", ["W", "C", "H", "R", "S"], index=0)

        advanced = st.expander("Additional transaction attributes")
        with advanced:
            a1, a2, a3, a4 = st.columns(4)
            payer_domain = a1.text_input("Payer email domain", value="gmail.com")
            device_type = a2.selectbox("Device type", ["desktop", "mobile"], index=0)
            card_network = a3.selectbox("Card network", ["visa", "mastercard", "american express", "discover"], index=0)
            card_type = a4.selectbox("Card type", ["debit", "credit"], index=0)

        submitted = st.form_submit_button("Run LinkRisk", type="primary", use_container_width=True)

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
        st.info("No payments yet. Submit the first transaction above. It should start with no matured relationship memory and therefore exercise the exact baseline fallback.")
    else:
        st.dataframe(
            feed.iloc[::-1],
            use_container_width=True,
            hide_index=True,
        )

        transaction_ids = engine.transaction_ids
        default_id = st.session_state.selected_transaction or transaction_ids[-1]
        default_index = transaction_ids.index(default_id) if default_id in transaction_ids else len(transaction_ids) - 1
        selected = st.selectbox(
            "Investigate transaction",
            transaction_ids,
            index=default_index,
        )
        st.session_state.selected_transaction = selected
        record = engine.get_record(selected)

        st.divider()
        st.markdown(f"### 3 · Transaction investigator — {selected}")
        left, right = st.columns([1.05, 1.35])

        with left:
            render_decision(record)
            render_evidence(record)

            st.markdown("#### Adjudication / feedback")
            status = record["adjudication"]
            if status["state"] == "unadjudicated":
                st.caption("No confirmed outcome is known yet. This transaction cannot influence fraud feedback memory.")
            elif status["state"] == "pending":
                hours = status["seconds_remaining"] / 3600.0
                st.warning(f"{status['outcome'].title()} outcome recorded. Feedback becomes usable in {hours:.1f} hours.")
            else:
                st.success(f"{status['outcome'].title()} outcome is matured and eligible for future relationship memory.")

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
                st.caption("No strictly earlier session transaction shared a validated relationship key. Same-timestamp rows are intentionally excluded from one another.")
            st.plotly_chart(
                relationship_network_figure(network),
                use_container_width=True,
                config={"displayModeBar": False},
            )
            st.caption("Cyan = current payment · purple = relationship view · red = matured fraud · green = matured legitimate · amber = recorded but not matured · gray = prior/unadjudicated.")

        with st.expander("Technical state used by the frozen specialist"):
            relationship_nonzero = {
                key: value
                for key, value in record["relationship_features"].items()
                if abs(float(value)) > 1e-12
            }
            feedback_nonzero = {
                key: value
                for key, value in record["feedback_features"].items()
                if abs(float(value)) > 1e-12
            }
            t1, t2 = st.columns(2)
            with t1:
                st.markdown("**Causal relationship features**")
                st.json(relationship_nonzero or {"state": "No prior relationship signal"})
            with t2:
                st.markdown("**Delayed feedback features**")
                st.json(feedback_nonzero or {"state": "No matured feedback signal"})

    st.divider()
    st.markdown("#### Suggested first walkthrough")
    st.markdown(
        "Submit `PROFILE-A / Windows`, mark that transaction **Confirmed fraud**, advance the clock by **72 hours**, then submit another payment with the same profile/device. The second payment is scored from the frozen model plus the now-matured relationship memory. Change the identifiers afterward to see the evidence disappear."
    )

with performance_tab:
    render_performance()
