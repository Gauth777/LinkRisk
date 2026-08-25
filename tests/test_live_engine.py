import numpy as np

from linkrisk.engine import FrozenChampionScorer
from linkrisk.feedback_features_v5 import LABEL_DELAY_SECONDS
from linkrisk.live_engine import (
    LiveLinkRiskEngine,
    LiveTransactionInput,
    live_input_to_model_row,
)


class IdentityPreprocessor:
    def transform(self, frame):
        return frame.to_numpy(dtype=np.float32)


class ConstantProbabilityModel:
    def __init__(self, score: float):
        self.score = float(score)

    def predict_proba(self, matrix):
        scores = np.full(len(matrix), self.score, dtype=float)
        return np.column_stack([1.0 - scores, scores])


def _engine() -> LiveLinkRiskEngine:
    scorer = FrozenChampionScorer(
        preprocessor=IdentityPreprocessor(),
        baseline_model=ConstantProbabilityModel(0.20),
        specialist_model=ConstantProbabilityModel(0.95),
        baseline_features=["TransactionAmt"],
    )
    return LiveLinkRiskEngine(scorer)


def _event(profile="P-A", device="D-A") -> LiveTransactionInput:
    return LiveTransactionInput(
        amount=2500.0,
        payment_profile=profile,
        device_info=device,
        receiver_domain="gmail.com",
        browser_context="chrome 63.0",
    )


def test_live_adapter_is_stable_for_repeated_payment_profile():
    left = live_input_to_model_row(_event("P-1", "D-1"), transaction_id="A", transaction_time=0)
    right = live_input_to_model_row(_event("P-1", "D-2"), transaction_id="B", transaction_time=5)
    other = live_input_to_model_row(_event("P-2", "D-1"), transaction_id="C", transaction_time=10)

    for column in ("card1", "card2", "card3", "card5", "addr1"):
        assert left[column] == right[column]
    assert left["card1"] != other["card1"]


def test_live_engine_applies_delayed_adjudicated_memory_to_future_payment():
    engine = _engine()

    first = engine.score_event(_event(), transaction_id="TX-A")
    assert first["decision"]["linkrisk_risk"] == 0.20
    assert first["decision"]["action"] == "ALLOW"
    assert first["feedback_features"]["feedback_confidence"] == 0.0

    engine.adjudicate("TX-A", "fraud")
    engine.advance_time(LABEL_DELAY_SECONDS - 1)
    before = engine.score_event(_event(), transaction_id="TX-B")
    assert before["feedback_features"]["feedback_confidence"] == 0.0
    assert before["decision"]["linkrisk_risk"] == 0.20

    engine.advance_time(2)
    after = engine.score_event(_event(), transaction_id="TX-C")
    assert after["feedback_features"]["confirmed_fraud_channels"] >= 2.0
    assert after["feedback_features"]["any_strong_confirmed_fraud"] == 1.0
    assert after["decision"]["graph_confidence"] > 0.0
    assert after["decision"]["linkrisk_risk"] > 0.20
    assert after["decision"]["action"] == "REVIEW"

    kinds = {node["kind"] for node in after["network"]["nodes"]}
    assert "fraud" in kinds
    assert "relation" in kinds


def test_same_timestamp_payments_do_not_see_one_another():
    engine = _engine()
    engine.score_event(_event(), transaction_id="TX-A")
    second = engine.score_event(_event(), transaction_id="TX-B")

    assert second["relationship_features"]["log_profile_prior_total"] == 0.0
    assert second["network"]["edges"] == []


def test_adjudication_status_matures_only_after_delay():
    engine = _engine()
    engine.score_event(_event(), transaction_id="TX-A")
    engine.adjudicate("TX-A", "fraud")

    assert engine.adjudication_status("TX-A")["state"] == "pending"
    engine.advance_time(LABEL_DELAY_SECONDS)
    assert engine.adjudication_status("TX-A")["state"] == "matured"
