import numpy as np
import pandas as pd

from linkrisk.engine import FrozenChampionScorer
from linkrisk.live_capacity_v2 import CausalCapacityController
from linkrisk.live_engine import LiveTransactionInput
from linkrisk.live_engine_v2 import LiveLinkRiskEngineV2
from linkrisk.mentalist_features_v7 import MENTALIST_FAMILIES, clue_activations
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


class CountingMentalistScorer:
    def __init__(self, *, score: float = 0.90, active_clues: bool = True):
        self.score = float(score)
        self.calls = 0
        self.policy = MentalistRuntimePolicy(
            version="mentalist-test-v2",
            min_clue_families=2,
            jane_score_threshold=0.80,
            baseline_review_threshold=0.85,
            v5_verify_displacement_threshold=0.12,
            validation_intervention_target=0.06,
        )
        threshold = -1.0 if active_clues else 999.0
        self.clue_thresholds = {
            family: {column: threshold for column in columns}
            for family, columns in MENTALIST_FAMILIES.items()
        }

    def score_batch(self, proactive_features, baseline_risk):
        self.calls += 1
        clues = clue_activations(proactive_features, self.clue_thresholds)
        n = len(proactive_features)
        return MentalistState(
            jane_scores=np.full(n, self.score, dtype=float),
            clue_count=clues["independent_clue_count"].to_numpy(dtype=int),
            clue_frame=clues,
        )


def _champion(baseline_score: float = 0.20, specialist_score: float = 0.95):
    return FrozenChampionScorer(
        preprocessor=IdentityPreprocessor(),
        baseline_model=ConstantProbabilityModel(baseline_score),
        specialist_model=ConstantProbabilityModel(specialist_score),
        baseline_features=["TransactionAmt"],
    )


def _event(profile="P-A"):
    return LiveTransactionInput(
        amount=2500.0,
        payment_profile=profile,
        device_info="Windows",
        receiver_domain="gmail.com",
        browser_context="chrome 65.0",
    )


def test_mentalist_model_is_bypassed_when_cheap_clues_do_not_pass():
    mentalist = CountingMentalistScorer(active_clues=False)
    engine = LiveLinkRiskEngineV2(_champion(), mentalist_scorer=mentalist)

    record = engine.score_event(_event(), transaction_id="TX-BYPASS")

    assert mentalist.calls == 0
    assert record["mentalist"]["invoked"] is False
    assert record["mentalist"]["bypassed"] is True
    assert record["decision"]["action"] == "ALLOW"
    assert record["decision"]["routing_reason"] == "MENTALIST_BYPASSED_EVIDENCE_GATE"


def test_evidence_bearing_allow_invokes_mentalist_and_can_verify():
    mentalist = CountingMentalistScorer(score=0.90, active_clues=True)
    engine = LiveLinkRiskEngineV2(_champion(), mentalist_scorer=mentalist)

    record = engine.score_event(_event(), transaction_id="TX-JANE")

    assert mentalist.calls == 1
    assert record["mentalist"]["invoked"] is True
    assert record["mentalist"]["candidate"] is True
    assert record["mentalist"]["promoted_by_jane"] is True
    assert record["decision"]["v5_action"] == "ALLOW"
    assert record["decision"]["action"] == "VERIFY"
    assert record["decision"]["routing_reason"] == "MENTALIST_CAPACITY_AUTHORIZED"


def test_review_is_immutable_and_does_not_invoke_mentalist():
    mentalist = CountingMentalistScorer(score=0.99, active_clues=True)
    engine = LiveLinkRiskEngineV2(
        _champion(baseline_score=0.95, specialist_score=0.95),
        mentalist_scorer=mentalist,
    )

    record = engine.score_event(_event(), transaction_id="TX-REVIEW")

    assert mentalist.calls == 0
    assert record["decision"]["v5_action"] == "REVIEW"
    assert record["decision"]["action"] == "REVIEW"
    assert record["decision"]["routing_reason"].startswith("V5_REVIEW_MANDATORY")


def test_live_capacity_can_defer_second_proactive_verify():
    mentalist = CountingMentalistScorer(score=0.90, active_clues=True)
    controller = CausalCapacityController(
        total_rate=0.06,
        mentalist_rate=0.01,
        total_burst=1.0,
        mentalist_burst=1.0,
    )
    engine = LiveLinkRiskEngineV2(
        _champion(),
        mentalist_scorer=mentalist,
        capacity_controller=controller,
    )

    first = engine.score_event(_event("P-1"), transaction_id="TX-1")
    second = engine.score_event(_event("P-2"), transaction_id="TX-2")

    assert first["decision"]["action"] == "VERIFY"
    assert second["decision"]["action"] == "ALLOW"
    assert second["decision"]["routing_reason"] == "MENTALIST_TOTAL_CAPACITY_DEFERRED"


def test_capacity_status_reports_reasoning_usage():
    mentalist = CountingMentalistScorer(active_clues=False)
    engine = LiveLinkRiskEngineV2(_champion(), mentalist_scorer=mentalist)
    engine.score_event(_event(), transaction_id="TX-1")
    engine.score_event(_event("P-2"), transaction_id="TX-2")

    status = engine.capacity_status()
    assert status["transactions_seen"] == 2
    assert status["mentalist_invoked"] == 0
    assert status["mentalist_bypassed"] == 2


def test_review_can_request_jane_second_opinion_without_changing_action_or_capacity():
    mentalist = CountingMentalistScorer(score=0.99, active_clues=True)
    engine = LiveLinkRiskEngineV2(
        _champion(baseline_score=0.95, specialist_score=0.95),
        mentalist_scorer=mentalist,
    )

    record = engine.score_event(_event(), transaction_id="TX-REVIEW-JANE")
    before = engine.capacity_status().copy()

    assert record["decision"]["action"] == "REVIEW"
    assert record["mentalist"]["invoked"] is False
    assert mentalist.calls == 0

    investigated = engine.deep_investigate("TX-REVIEW-JANE")
    after = engine.capacity_status().copy()

    assert mentalist.calls == 1
    assert investigated["decision"]["action"] == "REVIEW"
    assert investigated["analyst_jane"]["requested"] is True
    assert investigated["analyst_jane"]["invocation_mode"] == "analyst_requested"
    assert investigated["analyst_jane"]["corroborates_intervention"] is True
    assert investigated["analyst_jane"]["action_changed"] is False
    assert investigated["analyst_jane"]["capacity_consumed"] is False
    assert investigated["analyst_jane"]["uses_confirmed_fraud_as_input"] is False
    assert before == after

    # Idempotent repeat: the stored transaction-time deduction is reused.
    engine.deep_investigate("TX-REVIEW-JANE")
    assert mentalist.calls == 1
