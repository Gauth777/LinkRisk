from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from linkrisk.mentalist_features_v7 import (
    MENTALIST_FEATURES,
    clue_activations,
)


RUNTIME_POLICY_FILENAME = "mentalist_runtime_policy.json"


@dataclass(frozen=True)
class MentalistRuntimePolicy:
    """Frozen per-transaction operating boundaries for Mentalist v1.0.

    The thresholds are development/validation-calibrated operating boundaries,
    not fraud probabilities. REVIEW remains owned by the frozen v0.5 policy.
    """

    version: str
    min_clue_families: int
    jane_score_threshold: float
    v5_verify_displacement_threshold: float
    validation_intervention_target: float

    @classmethod
    def from_artifact(cls, root: str | Path) -> "MentalistRuntimePolicy":
        path = Path(root) / "artifacts" / "results" / RUNTIME_POLICY_FILENAME
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return cls(
            version=str(payload["version"]),
            min_clue_families=int(payload["min_clue_families"]),
            jane_score_threshold=float(payload["jane_score_threshold"]),
            v5_verify_displacement_threshold=float(
                payload["v5_verify_displacement_threshold"]
            ),
            validation_intervention_target=float(
                payload["validation_intervention_target"]
            ),
        )

    def validate(self) -> None:
        if self.min_clue_families < 1:
            raise ValueError("min_clue_families must be >= 1")
        for name, value in (
            ("jane_score_threshold", self.jane_score_threshold),
            (
                "v5_verify_displacement_threshold",
                self.v5_verify_displacement_threshold,
            ),
            ("validation_intervention_target", self.validation_intervention_target),
        ):
            if not np.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if not 0.0 <= self.jane_score_threshold <= 1.0:
            raise ValueError("jane_score_threshold must lie in [0, 1]")
        if not 0.0 <= self.v5_verify_displacement_threshold <= 1.0:
            raise ValueError(
                "v5_verify_displacement_threshold must lie in [0, 1]"
            )
        if not 0.0 < self.validation_intervention_target < 1.0:
            raise ValueError("validation_intervention_target must lie in (0, 1)")


@dataclass(frozen=True)
class MentalistState:
    jane_scores: np.ndarray
    clue_count: np.ndarray
    clue_frame: pd.DataFrame


@dataclass(frozen=True)
class RuntimeRoutingResult:
    actions: np.ndarray
    reasons: np.ndarray
    promoted_by_jane: np.ndarray
    displaced_v5_verify: np.ndarray

    @property
    def intervention_delta(self) -> int:
        promoted = int(self.promoted_by_jane.sum())
        displaced = int(self.displaced_v5_verify.sum())
        return promoted - displaced


@dataclass
class FrozenMentalistScorer:
    """Score proactive evidence without consuming current/prior fraud labels."""

    model: Any
    clue_thresholds: dict[str, dict[str, float]]
    policy: MentalistRuntimePolicy

    @classmethod
    def from_artifacts(cls, root: str | Path) -> "FrozenMentalistScorer":
        root_path = Path(root)
        model_path = root_path / "artifacts" / "models" / "mentalist_v7_candidate.joblib"
        result_dir = root_path / "artifacts" / "results"
        with (result_dir / "mentalist_v7_validation.json").open(
            "r", encoding="utf-8"
        ) as handle:
            v7 = json.load(handle)

        policy = MentalistRuntimePolicy.from_artifact(root_path)
        policy.validate()
        return cls(
            model=joblib.load(model_path),
            clue_thresholds=v7["clue_thresholds"],
            policy=policy,
        )

    def score_batch(
        self,
        proactive_features: pd.DataFrame,
        baseline_risk: pd.Series | np.ndarray,
    ) -> MentalistState:
        baseline = np.asarray(baseline_risk, dtype=float)
        if len(baseline) != len(proactive_features):
            raise ValueError("baseline_risk and proactive_features must align")

        x = proactive_features[MENTALIST_FEATURES].copy()
        x.insert(0, "baseline_oof_risk", baseline)
        x = x.replace([np.inf, -np.inf], np.nan).fillna(0.0).astype(np.float32)
        scores = self.model.predict_proba(x)[:, 1]

        clues = clue_activations(proactive_features, self.clue_thresholds)
        counts = clues["independent_clue_count"].to_numpy(dtype=int)
        return MentalistState(
            jane_scores=np.asarray(scores, dtype=float),
            clue_count=counts,
            clue_frame=clues,
        )


def apply_runtime_policy(
    *,
    v5_actions: np.ndarray,
    v5_risk: np.ndarray,
    mentalist_state: MentalistState,
    policy: MentalistRuntimePolicy,
) -> RuntimeRoutingResult:
    """Apply the frozen v1.0 decision boundaries independently per row.

    This function is deliberately label-free and future-traffic-free. It converts
    the successful batch allocation into a deployable threshold contract. The
    subsequent validation reproduction script must prove that these boundaries
    reproduce v1.0 before the held-out test can be opened.
    """
    policy.validate()
    actions_in = np.asarray(v5_actions, dtype=object)
    risk = np.asarray(v5_risk, dtype=float)
    jane = np.asarray(mentalist_state.jane_scores, dtype=float)
    clues = np.asarray(mentalist_state.clue_count, dtype=int)
    n = len(actions_in)
    if any(len(array) != n for array in (risk, jane, clues)):
        raise ValueError("All runtime routing arrays must have equal length")

    valid = np.isin(actions_in, ["ALLOW", "VERIFY", "REVIEW"])
    if not bool(valid.all()):
        raise ValueError("v5_actions contains an unknown action")

    review = actions_in == "REVIEW"
    verify = actions_in == "VERIFY"
    allow = actions_in == "ALLOW"

    promoted = (
        allow
        & (clues >= policy.min_clue_families)
        & (jane >= policy.jane_score_threshold)
    )
    displaced = verify & (risk <= policy.v5_verify_displacement_threshold)

    actions = actions_in.copy()
    reasons = np.full(n, "V5_ALLOW", dtype=object)
    reasons[review] = "V5_REVIEW"
    reasons[verify] = "V5_VERIFY_RETAINED"

    actions[displaced] = "ALLOW"
    reasons[displaced] = "V5_VERIFY_DISPLACED_BY_RUNTIME_BOUNDARY"

    actions[promoted] = "VERIFY"
    reasons[promoted] = "MENTALIST_PROACTIVE"

    if not bool(np.all(actions[review] == "REVIEW")):
        raise AssertionError("Frozen v0.5 REVIEW decision changed")

    return RuntimeRoutingResult(
        actions=actions,
        reasons=reasons,
        promoted_by_jane=promoted,
        displaced_v5_verify=displaced,
    )
