import numpy as np
import pandas as pd

from linkrisk.engine import FrozenChampionScorer
from linkrisk.feedback_schema import FEEDBACK_FEATURES_V5
from linkrisk.relationship_features_v4 import RELATIONSHIP_FEATURES_V4


class IdentityPreprocessor:
    def transform(self, frame):
        return frame.to_numpy(dtype=np.float32)


class FixedProbabilityModel:
    def __init__(self, scores):
        self.scores = np.asarray(scores, dtype=float)

    def predict_proba(self, matrix):
        scores = self.scores[: len(matrix)]
        return np.column_stack([1.0 - scores, scores])


def test_frozen_champion_scorer_preserves_fallback_and_review():
    transactions = pd.DataFrame(
        {
            "TransactionID": [1, 2],
            "feature": [0.1, 0.2],
        },
        index=[10, 11],
    )
    relationship = pd.DataFrame(
        0.0,
        index=transactions.index,
        columns=RELATIONSHIP_FEATURES_V4,
    )
    feedback = pd.DataFrame(
        0.0,
        index=transactions.index,
        columns=[*FEEDBACK_FEATURES_V5, "feedback_confidence"],
    )
    feedback.loc[11, "feedback_confidence"] = 1.0
    feedback.loc[11, "any_strong_confirmed_fraud"] = 1.0

    scorer = FrozenChampionScorer(
        preprocessor=IdentityPreprocessor(),
        baseline_model=FixedProbabilityModel([0.20, 0.20]),
        specialist_model=FixedProbabilityModel([0.90, 0.90]),
        baseline_features=["feature"],
    )

    result = scorer.score_batch(transactions, relationship, feedback)

    assert result.loc[10, "linkrisk_risk"] == 0.20
    assert result.loc[10, "model_path"] == "baseline_fallback"
    assert result.loc[10, "action"] == "ALLOW"
    assert np.isclose(result.loc[11, "linkrisk_risk"], 0.90)
    assert result.loc[11, "action"] == "REVIEW"


def test_frozen_champion_scorer_requires_aligned_indexes():
    transactions = pd.DataFrame({"feature": [0.1]}, index=[1])
    relationship = pd.DataFrame(0.0, index=[2], columns=RELATIONSHIP_FEATURES_V4)
    feedback = pd.DataFrame(
        0.0,
        index=[1],
        columns=[*FEEDBACK_FEATURES_V5, "feedback_confidence"],
    )
    scorer = FrozenChampionScorer(
        preprocessor=IdentityPreprocessor(),
        baseline_model=FixedProbabilityModel([0.2]),
        specialist_model=FixedProbabilityModel([0.2]),
        baseline_features=["feature"],
    )

    try:
        scorer.score_batch(transactions, relationship, feedback)
    except ValueError as exc:
        assert "indexes must align" in str(exc)
    else:
        raise AssertionError("Expected misaligned indexes to be rejected")
