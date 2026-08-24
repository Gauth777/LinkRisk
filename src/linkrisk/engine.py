from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from linkrisk.decision import score_transaction
from linkrisk.feedback_schema import FEEDBACK_CONFIDENCE_COLUMN, feedback_matrix_v5
from linkrisk.relationship_features_v4 import relationship_matrix_v4


@dataclass
class FrozenChampionScorer:
    """Runtime wrapper for the frozen LinkRisk v0.5 champion.

    The scorer consumes current transaction rows plus already-computed causal
    relationship/feedback state. State construction remains separate so the
    runtime path cannot accidentally consume current or future labels.
    """

    preprocessor: Any
    baseline_model: Any
    specialist_model: Any
    baseline_features: list[str]

    @classmethod
    def from_artifacts(cls, root: str | Path) -> "FrozenChampionScorer":
        root_path = Path(root)
        model_dir = root_path / "artifacts" / "models"
        result_dir = root_path / "artifacts" / "results"

        with (result_dir / "baseline_features.json").open("r", encoding="utf-8") as f:
            baseline_features = json.load(f)

        return cls(
            preprocessor=joblib.load(model_dir / "baseline_preprocessor.joblib"),
            baseline_model=joblib.load(model_dir / "baseline_xgboost.joblib"),
            specialist_model=joblib.load(model_dir / "feedback_specialist_v5.joblib"),
            baseline_features=baseline_features,
        )

    def score_batch(
        self,
        transactions: pd.DataFrame,
        relationship_features: pd.DataFrame,
        feedback_features: pd.DataFrame,
        *,
        transaction_id_column: str = "TransactionID",
    ) -> pd.DataFrame:
        """Score an aligned batch through baseline, specialist, gate, policy, and evidence."""
        if not transactions.index.equals(relationship_features.index):
            raise ValueError("transactions and relationship_features indexes must align")
        if not transactions.index.equals(feedback_features.index):
            raise ValueError("transactions and feedback_features indexes must align")
        if FEEDBACK_CONFIDENCE_COLUMN not in feedback_features.columns:
            raise KeyError(f"Missing {FEEDBACK_CONFIDENCE_COLUMN}")

        raw_matrix = np.asarray(
            self.preprocessor.transform(transactions[self.baseline_features]),
            dtype=np.float32,
        )
        graph_matrix = relationship_matrix_v4(relationship_features)
        feedback_matrix = feedback_matrix_v5(feedback_features)
        specialist_matrix = np.hstack(
            [raw_matrix, graph_matrix, feedback_matrix]
        ).astype(np.float32, copy=False)

        baseline_scores = self.baseline_model.predict_proba(raw_matrix)[:, 1]
        specialist_scores = self.specialist_model.predict_proba(specialist_matrix)[:, 1]
        confidence = feedback_features[FEEDBACK_CONFIDENCE_COLUMN].to_numpy(dtype=float)

        transaction_ids = (
            transactions[transaction_id_column].tolist()
            if transaction_id_column in transactions.columns
            else [None] * len(transactions)
        )

        rows: list[dict[str, Any]] = []
        for pos, index in enumerate(transactions.index):
            feedback = feedback_features.loc[index].to_dict()
            decision = score_transaction(
                baseline_risk=float(baseline_scores[pos]),
                specialist_risk=float(specialist_scores[pos]),
                graph_confidence=float(confidence[pos]),
                feedback=feedback,
                transaction_id=transaction_ids[pos],
            )
            payload = decision.to_dict()
            payload["source_index"] = index
            rows.append(payload)

        return pd.DataFrame(rows).set_index("source_index")
