from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from typing import Deque

import numpy as np
import pandas as pd

from linkrisk.baseline import TIME_COL
from linkrisk.relationship_features_v4 import (
    DEVICE_CONTEXT_COLUMNS,
    PAYMENT_PROFILE_COLUMNS,
    build_relationship_features_v4,
    make_composite_key,
)

WINDOW_10M = 10 * 60
WINDOW_1H = 60 * 60

# v0.7 deliberately uses a compact set of causal, interpretable measurements.
# No current/prior fraud labels are inputs to this feature builder.
MENTALIST_RELATIONSHIP_FEATURES = [
    "log_profile_prior_10m",
    "profile_acceleration_10m_vs_1h",
    "profile_amount_abs_log_ratio",
    "known_profile_new_deviceinfo",
    "known_profile_new_browser",
    "log_strong_device_prior_1h",
    "log_strong_receiver_prior_1h",
    "log_device_context_prior_profiles",
    "device_context_new_profile",
]

MENTALIST_MOTIF_FEATURES = [
    "log_context_tx_10m",
    "log_context_tx_1h",
    "log_context_unique_profiles_10m",
    "log_context_unique_profiles_1h",
    "context_profile_diversity_1h",
    "context_new_profile_1h",
    "log_profile_unique_contexts_1h",
    "profile_context_diversity_1h",
    "profile_new_context_1h",
]

MENTALIST_DERIVED_FEATURES = ["abs_profile_amount_zscore"]
MENTALIST_FEATURES = (
    MENTALIST_RELATIONSHIP_FEATURES
    + MENTALIST_MOTIF_FEATURES
    + MENTALIST_DERIVED_FEATURES
)

# Evidence families are for diagnostics/explanations. The model receives the
# raw measurements above; clue counts do not hard-code a fraud decision.
MENTALIST_FAMILIES = {
    "velocity": [
        "log_profile_prior_10m",
        "profile_acceleration_10m_vs_1h",
        "log_context_tx_10m",
        "log_context_tx_1h",
    ],
    "behavior_change": [
        "profile_amount_abs_log_ratio",
        "abs_profile_amount_zscore",
        "known_profile_new_deviceinfo",
        "known_profile_new_browser",
    ],
    "coordination": [
        "log_context_unique_profiles_10m",
        "log_context_unique_profiles_1h",
        "context_profile_diversity_1h",
        "context_new_profile_1h",
        "log_device_context_prior_profiles",
        "device_context_new_profile",
    ],
    "reuse_churn": [
        "log_strong_device_prior_1h",
        "log_strong_receiver_prior_1h",
        "log_profile_unique_contexts_1h",
        "profile_context_diversity_1h",
        "profile_new_context_1h",
    ],
}


@dataclass
class RollingEntityWindow:
    recent_10m: Deque[tuple[float, str | None]] = field(default_factory=deque)
    recent_1h: Deque[tuple[float, str | None]] = field(default_factory=deque)
    entities_10m: Counter[str] = field(default_factory=Counter)
    entities_1h: Counter[str] = field(default_factory=Counter)

    @staticmethod
    def _drop(
        queue: Deque[tuple[float, str | None]],
        counts: Counter[str],
        cutoff: float,
    ) -> None:
        while queue and queue[0][0] < cutoff:
            _, entity = queue.popleft()
            if entity is None:
                continue
            counts[entity] -= 1
            if counts[entity] <= 0:
                del counts[entity]

    def prune(self, now: float) -> None:
        self._drop(self.recent_10m, self.entities_10m, now - WINDOW_10M)
        self._drop(self.recent_1h, self.entities_1h, now - WINDOW_1H)

    def add(self, now: float, entity: str | None) -> None:
        self.recent_10m.append((now, entity))
        self.recent_1h.append((now, entity))
        if entity is not None:
            self.entities_10m[entity] += 1
            self.entities_1h[entity] += 1


def _as_key(value: object) -> str | None:
    return None if pd.isna(value) else str(value)


def build_coordination_motifs_v7(frame: pd.DataFrame) -> pd.DataFrame:
    """Build strictly-causal short-horizon coordination motifs.

    A device context is the existing v4 composite of DeviceInfo + id_31.
    A payment profile is the existing masked composite used by v4. These are
    pseudo-entities, not claims about real customer identity.

    Rows sharing an exact timestamp cannot see one another: the whole timestamp
    batch is scored before any row from that timestamp enters history.
    """
    required = {TIME_COL, *PAYMENT_PROFILE_COLUMNS, *DEVICE_CONTEXT_COLUMNS}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise KeyError(f"Missing Mentalist motif columns: {missing}")

    working = frame.copy()
    working["_mentalist_profile"] = make_composite_key(
        working, PAYMENT_PROFILE_COLUMNS
    )
    working["_mentalist_context"] = make_composite_key(
        working, DEVICE_CONTEXT_COLUMNS
    )
    working = working.sort_values(TIME_COL, kind="mergesort")

    n = len(working)
    timestamps = working[TIME_COL].to_numpy(dtype=float)
    profile_keys = working["_mentalist_profile"].astype("object").to_numpy()
    context_keys = working["_mentalist_context"].astype("object").to_numpy()

    arrays = {
        name: np.zeros(n, dtype=np.float32) for name in MENTALIST_MOTIF_FEATURES
    }
    context_history: dict[str, RollingEntityWindow] = defaultdict(RollingEntityWindow)
    profile_history: dict[str, RollingEntityWindow] = defaultdict(RollingEntityWindow)

    start = 0
    while start < n:
        now = float(timestamps[start])
        end = start + 1
        while end < n and timestamps[end] == now:
            end += 1

        # Snapshot only prior timestamps.
        for pos in range(start, end):
            profile = _as_key(profile_keys[pos])
            context = _as_key(context_keys[pos])

            if context is not None:
                history = context_history.get(context)
                if history is not None:
                    history.prune(now)
                    tx10 = len(history.recent_10m)
                    tx1h = len(history.recent_1h)
                    profiles10 = len(history.entities_10m)
                    profiles1h = len(history.entities_1h)
                    arrays["log_context_tx_10m"][pos] = np.log1p(tx10)
                    arrays["log_context_tx_1h"][pos] = np.log1p(tx1h)
                    arrays["log_context_unique_profiles_10m"][pos] = np.log1p(
                        profiles10
                    )
                    arrays["log_context_unique_profiles_1h"][pos] = np.log1p(
                        profiles1h
                    )
                    arrays["context_profile_diversity_1h"][pos] = (
                        profiles1h / max(tx1h, 1)
                    )
                    if tx1h > 0 and profile is not None:
                        arrays["context_new_profile_1h"][pos] = float(
                            profile not in history.entities_1h
                        )

            if profile is not None:
                history = profile_history.get(profile)
                if history is not None:
                    history.prune(now)
                    tx1h = len(history.recent_1h)
                    contexts1h = len(history.entities_1h)
                    arrays["log_profile_unique_contexts_1h"][pos] = np.log1p(
                        contexts1h
                    )
                    arrays["profile_context_diversity_1h"][pos] = (
                        contexts1h / max(tx1h, 1)
                    )
                    if tx1h > 0 and context is not None:
                        arrays["profile_new_context_1h"][pos] = float(
                            context not in history.entities_1h
                        )

        # Only after scoring the timestamp batch may it become history.
        for pos in range(start, end):
            profile = _as_key(profile_keys[pos])
            context = _as_key(context_keys[pos])
            if context is not None:
                context_history[context].prune(now)
                context_history[context].add(now, profile)
            if profile is not None:
                profile_history[profile].prune(now)
                profile_history[profile].add(now, context)

        start = end

    output = pd.DataFrame(arrays, index=working.index)
    return output.reindex(frame.index)


def build_mentalist_features_v7(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the frozen proactive v0.7 feature set in model order."""
    relationship = build_relationship_features_v4(frame)
    motifs = build_coordination_motifs_v7(frame)

    output = relationship[MENTALIST_RELATIONSHIP_FEATURES].copy()
    output = output.join(motifs[MENTALIST_MOTIF_FEATURES])
    output["abs_profile_amount_zscore"] = relationship[
        "profile_amount_zscore"
    ].abs()
    output = output.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return output[MENTALIST_FEATURES].astype(np.float32, copy=False)


def calibrate_clue_thresholds(
    features: pd.DataFrame,
    labels: pd.Series | np.ndarray,
    *,
    quantile: float = 0.975,
) -> dict[str, dict[str, float]]:
    """Calibrate 'unusual' clue thresholds from legitimate training traffic.

    These thresholds are diagnostic/explanatory only. They do not decide fraud.
    A family becomes active when at least one of its measurements exceeds what
    is typical for the supplied legitimate training population.
    """
    if not 0.5 < quantile < 1.0:
        raise ValueError("quantile must lie between 0.5 and 1.0")
    y = pd.Series(np.asarray(labels), index=features.index)
    legitimate = features.loc[y == 0]
    if legitimate.empty:
        raise ValueError("Need legitimate training rows to calibrate clues")

    thresholds: dict[str, dict[str, float]] = {}
    for family, columns in MENTALIST_FAMILIES.items():
        thresholds[family] = {
            column: float(legitimate[column].quantile(quantile))
            for column in columns
        }
    return thresholds


def clue_activations(
    features: pd.DataFrame,
    thresholds: dict[str, dict[str, float]],
) -> pd.DataFrame:
    """Return independent evidence-family activations for diagnostics."""
    output = pd.DataFrame(index=features.index)
    for family, columns in MENTALIST_FAMILIES.items():
        family_thresholds = thresholds[family]
        active = pd.Series(False, index=features.index)
        for column in columns:
            active |= features[column] > float(family_thresholds[column])
        output[f"clue_{family}"] = active.astype(np.int8)
    clue_columns = [f"clue_{family}" for family in MENTALIST_FAMILIES]
    output["independent_clue_count"] = output[clue_columns].sum(axis=1).astype(np.int8)
    return output
