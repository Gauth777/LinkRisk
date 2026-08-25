import numpy as np
import pandas as pd

from linkrisk.engine import FrozenChampionScorer
from linkrisk.feedback_features_v5 import LABEL_DELAY_SECONDS
from linkrisk.live_engine import (
    LiveLinkRiskEngine,
    LiveTransactionInput,
    live_input_to_model_row,
)
from linkrisk.mentalist_runtime_policy import MentalistRuntimePolicy, MentalistState


class IdentityPreprocessor:
    def transform(self, frame):
        return frame.to_numpy(dtype=np.float32)


class ConstantProbabilityModel:
    def __init__(self, score: float):
        self.score = float(score)

    def predict_proba(self, matrix):
        scores = np.full(len(matrix), self.score, dtype=float)
        return np.column_stack([1.0 - scores, scores])


class FakeMentalistScorer:
    def __init__(self, score: float = 0.90, clue_count: int = 2):
        self.score = float(score)
        self.clue_count = int(clue_count)
        self.policy = MentalistRuntimePolicy(
            version="mentalist-test",
            min_clue_families=2,
            jane_score_threshold=0.80,
            baseline_review_threshold=0.85,
            v5_verify_displacement_threshold=0.12,
            validation_intervention_target=0.06,
        )

    def score_batch(self, proactive_features, baseline_risk):
        n = len(proactive_features)
        active = self.clue_count >= 2
        frame = pd.DataFrame(
            {
                "clue_velocity": np.full(n, int(active), dtype=np.int8),
                "clue_behavior_change": np.zeros(n, dtype=np.int8),
                "clue_coordination": np.full(n, int(active), dtype=np.int8),
                "clue_reuse_churn": np.zeros(n, dtype=np.int8),
                "independent_clue_count": np.full(n, self.clue_count, dtype=np.int8),
            },
            index=proactive_features.index,
        )
        return MentalistState(
            jane_scores=np.full(n, self.score, dtype=float),
            clue_count=np.full(n, self.clue_count, dtype=int),
            clue_frame=frame,
        )


def _engine(
    *,
    baseline_score: float = 0.20,
    specialist_score: float = 0.95,
    mentalist=None,
) -> LiveLinkRiskEngine:
    scorer = FrozenChampionScorer(
        preprocessor=IdentityPreprocessor(),
        baseline_model=ConstantProbabilityModel(baseline_score),
        specialist_model=ConstantProbabilityModel(specialist_score),
        baseline_features=["TransactionAmt"],
    )
    return LiveLinkRiskEngine(scorer, mentalist_scorer=mentalist)


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


def test_late_adjudication_does_not_rewrite_an_earlier_decision():
    engine = _engine()
    engine.score_event(_event(), transaction_id="TX-A")
    engine.advance_time(LABEL_DELAY_SECONDS + 3600)

    before_adjudication = engine.score_event(_event(), transaction_id="TX-B")
    assert before_adjudication["feedback_features"]["feedback_confidence"] == 0.0

    engine.adjudicate("TX-A", "fraud")
    stored = engine.get_record("TX-B")
    assert stored["feedback_features"]["feedback_confidence"] == 0.0

    after_adjudication = engine.score_event(_event(), transaction_id="TX-C")
    assert after_adjudication["feedback_features"]["confirmed_fraud_channels"] >= 2.0


def test_mentalist_can_promote_allow_without_confirmed_fraud_history():
    engine = _engine(mentalist=FakeMentalistScorer(score=0.90, clue_count=2))
    record = engine.score_event(_event(), transaction_id="TX-JANE")

    assert record["decision"]["v5_action"] == "ALLOW"
    assert record["decision"]["action"] == "VERIFY"
    assert record["decision"]["routing_reason"] == "MENTALIST_PROACTIVE"
    assert record["mentalist"]["promoted_by_jane"] is True
    assert record["mentalist"]["uses_confirmed_fraud_as_input"] is False
    assert record["case_file"]["trusted_fraud_evidence_present"] is False
    assert record["case_file"]["action_changed"] is True


def test_mentalist_does_not_promote_with_only_one_clue_family():
    engine = _engine(mentalist=FakeMentalistScorer(score=0.99, clue_count=1))
    record = engine.score_event(_event(), transaction_id="TX-WEAK")

    assert record["decision"]["v5_action"] == "ALLOW"
    assert record["decision"]["action"] == "ALLOW"
    assert record["mentalist"]["promoted_by_jane"] is False


def test_v5_review_remains_immutable_under_mentalist():
    engine = _engine(
        baseline_score=0.95,
        specialist_score=0.95,
        mentalist=FakeMentalistScorer(score=0.99, clue_count=4),
    )
    record = engine.score_event(_event(), transaction_id="TX-REVIEW")

    assert record["decision"]["v5_action"] == "REVIEW"
    assert record["decision"]["action"] == "REVIEW"
    assert record["mentalist"]["promoted_by_jane"] is False


def test_feed_exposes_separate_v5_and_mentalist_channels():
    engine = _engine(mentalist=FakeMentalistScorer(score=0.90, clue_count=2))
    engine.score_event(_event(), transaction_id="TX-FEED")
    feed = engine.feed()

    assert feed.loc[0, "v0.5 Action"] == "ALLOW"
    assert feed.loc[0, "Action"] == "VERIFY"
    assert feed.loc[0, "Jane"] == 0.90
    assert feed.loc[0, "Clues"] == 2
