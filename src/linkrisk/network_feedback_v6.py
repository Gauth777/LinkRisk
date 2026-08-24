from __future__ import annotations

from collections import defaultdict, deque
import math

import numpy as np
import pandas as pd
from xgboost import XGBClassifier

from linkrisk.relationship_features_v4 import (
    DEVICE_CONTEXT_COLUMNS,
    PAYMENT_PROFILE_COLUMNS,
    STRONG_DEVICE_COLUMNS,
    STRONG_RECEIVER_COLUMNS,
    make_composite_key,
    relationship_matrix_v4,
)


TIME_COL = "TransactionDT"
LABEL_DELAY = 72 * 60 * 60
WINDOW_30D = 30 * 24 * 60 * 60
HALF_LIFE_14D = 14 * 24 * 60 * 60
GATE_GRID = [0.25, 0.50, 0.75, 1.00]

DIRECT_KEYS = {
    "profile": PAYMENT_PROFILE_COLUMNS,
    "device": STRONG_DEVICE_COLUMNS,
    "receiver": STRONG_RECEIVER_COLUMNS,
    "device_context": DEVICE_CONTEXT_COLUMNS,
}

# These are deliberately contextual bridges, not identity claims. They are used
# only for strictly prior two-hop neighbourhood propagation.
BRIDGE_KEYS = {
    "device_context": DEVICE_CONTEXT_COLUMNS,
    "receiver_context": ["addr1", "R_emaildomain"],
}

DIRECT_FEATURES: list[str] = []
for key in DIRECT_KEYS:
    DIRECT_FEATURES += [
        f"log_{key}_confirmed_total",
        f"log_{key}_confirmed_fraud_total",
        f"{key}_confirmed_fraud_rate",
        f"log_{key}_confirmed_fraud_30d",
        f"{key}_has_confirmed_fraud",
        f"{key}_fraud_recency_decay",
    ]

NETWORK_FEATURES = [
    "feedback_history_channels",
    "confirmed_fraud_channels",
    "any_strong_confirmed_fraud",
    "max_confirmed_fraud_rate",
    "feedback_total_support_log",
    "log_device_bridge_prior_profiles",
    "log_device_bridge_supported_profiles",
    "log_device_bridge_fraud_profiles",
    "device_bridge_max_fraud_rate",
    "device_bridge_fraud_recency_decay",
    "log_receiver_bridge_prior_profiles",
    "log_receiver_bridge_supported_profiles",
    "log_receiver_bridge_fraud_profiles",
    "receiver_bridge_max_fraud_rate",
    "receiver_bridge_fraud_recency_decay",
    "two_hop_supported_channels",
    "two_hop_fraud_channels",
    "log_two_hop_unique_fraud_profiles",
    "log_two_hop_confirmed_fraud_support",
    "log_two_hop_confirmed_fraud_30d",
    "two_hop_max_fraud_rate",
    "two_hop_fraud_recency_decay",
    "two_hop_multi_profile_corroboration",
]

FEEDBACK_FEATURES_V6 = DIRECT_FEATURES + NETWORK_FEATURES


class History:
    __slots__ = ("confirmed", "fraud", "fraud_times", "last_fraud_time")

    def __init__(self):
        self.confirmed = 0
        self.fraud = 0
        self.fraud_times = deque()
        self.last_fraud_time: float | None = None


def _prune_fraud_times(history: History, now: float) -> None:
    cutoff = now - WINDOW_30D
    while history.fraud_times and history.fraud_times[0] < cutoff:
        history.fraud_times.popleft()


def _recency_decay(last_time: float | None, now: float) -> float:
    if last_time is None:
        return 0.0
    age = max(now - last_time, 0.0)
    return float(math.exp(-math.log(2.0) * age / HALF_LIFE_14D))


def _history_snapshot(history: History | None, now: float) -> tuple[int, int, float, int, float]:
    if history is None or history.confirmed == 0:
        return 0, 0, 0.0, 0, 0.0
    _prune_fraud_times(history, now)
    rate = history.fraud / history.confirmed
    return (
        history.confirmed,
        history.fraud,
        rate,
        len(history.fraud_times),
        _recency_decay(history.last_fraud_time, now),
    )


def build_network_feedback_v6(
    frame: pd.DataFrame,
    label_eligible: pd.Series,
) -> pd.DataFrame:
    """Build delayed direct + two-hop confirmed-fraud graph memory.

    Safety invariants:
    - only rows with label_eligible=True may ever contribute labels;
    - those labels mature only after LABEL_DELAY;
    - validation labels can therefore be excluded entirely;
    - adjacency uses only strictly earlier observed transactions;
    - rows sharing the same TransactionDT cannot see each other.
    """
    required = {
        TIME_COL,
        "isFraud",
        *{column for columns in DIRECT_KEYS.values() for column in columns},
        *{column for columns in BRIDGE_KEYS.values() for column in columns},
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise KeyError(f"Missing columns required for v6 network feedback: {missing}")

    working = frame.copy()
    eligible = label_eligible.reindex(working.index).fillna(False).astype(bool)
    working["_label_eligible"] = eligible

    for name, columns in DIRECT_KEYS.items():
        working[f"_direct_{name}"] = make_composite_key(working, columns)
    for name, columns in BRIDGE_KEYS.items():
        working[f"_bridge_{name}"] = make_composite_key(working, columns)

    working = working.sort_values(TIME_COL, kind="mergesort")
    n = len(working)
    original_index = working.index.to_numpy()
    times = working[TIME_COL].to_numpy(dtype=float)
    labels = working["isFraud"].astype(np.int8).to_numpy()
    eligible_arr = working["_label_eligible"].to_numpy(dtype=bool)

    direct_arrays = {
        name: working[f"_direct_{name}"].astype("object").to_numpy()
        for name in DIRECT_KEYS
    }
    bridge_arrays = {
        name: working[f"_bridge_{name}"].astype("object").to_numpy()
        for name in BRIDGE_KEYS
    }
    profile_array = direct_arrays["profile"]

    histories: dict[str, dict[str, History]] = {
        name: defaultdict(History) for name in DIRECT_KEYS
    }
    # Prior-only graph adjacency: contextual bridge -> payment profiles seen on
    # earlier transactions. These observations do not use labels.
    bridge_profiles: dict[str, dict[str, set[str]]] = {
        name: defaultdict(set) for name in BRIDGE_KEYS
    }
    pending = deque()

    arrays = {
        feature: np.zeros(n, dtype=np.float32)
        for feature in FEEDBACK_FEATURES_V6
    }
    confidence = np.zeros(n, dtype=np.float32)

    start = 0
    while start < n:
        now = float(times[start])
        end = start + 1
        while end < n and times[end] == now:
            end += 1

        # Mature eligible training labels before scoring this timestamp batch.
        while pending and pending[0][0] <= now:
            _, original_time, label, stored_direct = pending.popleft()
            for name, key in stored_direct.items():
                if key is None:
                    continue
                history = histories[name][key]
                history.confirmed += 1
                if label == 1:
                    history.fraud += 1
                    history.fraud_times.append(original_time)
                    history.last_fraud_time = original_time

        # Score the entire same-time batch from the same prior state.
        for pos in range(start, end):
            history_channels = 0
            fraud_channels = 0
            total_support = 0
            max_direct_rate = 0.0
            strong_direct_fraud = 0.0

            for name in DIRECT_KEYS:
                raw_key = direct_arrays[name][pos]
                if pd.isna(raw_key):
                    continue
                history = histories[name].get(str(raw_key))
                confirmed, fraud, rate, fraud_30d, decay = _history_snapshot(history, now)
                if confirmed == 0:
                    continue

                arrays[f"log_{name}_confirmed_total"][pos] = np.log1p(confirmed)
                arrays[f"log_{name}_confirmed_fraud_total"][pos] = np.log1p(fraud)
                arrays[f"{name}_confirmed_fraud_rate"][pos] = rate
                arrays[f"log_{name}_confirmed_fraud_30d"][pos] = np.log1p(fraud_30d)
                arrays[f"{name}_has_confirmed_fraud"][pos] = float(fraud > 0)
                arrays[f"{name}_fraud_recency_decay"][pos] = decay

                history_channels += 1
                total_support += confirmed
                max_direct_rate = max(max_direct_rate, rate)
                if fraud > 0:
                    fraud_channels += 1
                    if name in {"device", "receiver"}:
                        strong_direct_fraud = 1.0

            arrays["feedback_history_channels"][pos] = history_channels
            arrays["confirmed_fraud_channels"][pos] = fraud_channels
            arrays["any_strong_confirmed_fraud"][pos] = strong_direct_fraud
            arrays["max_confirmed_fraud_rate"][pos] = max_direct_rate
            arrays["feedback_total_support_log"][pos] = np.log1p(total_support)

            current_profile_raw = profile_array[pos]
            current_profile = None if pd.isna(current_profile_raw) else str(current_profile_raw)
            two_hop_supported_channels = 0
            two_hop_fraud_channels = 0
            union_fraud_profiles: set[str] = set()
            bridge_fraud_profiles: dict[str, set[str]] = {}
            bridge_supported_profiles: dict[str, int] = {}
            bridge_prior_profiles: dict[str, int] = {}
            bridge_max_rate: dict[str, float] = {}
            bridge_max_decay: dict[str, float] = {}

            for bridge_name in BRIDGE_KEYS:
                raw_bridge = bridge_arrays[bridge_name][pos]
                neighbours: set[str] = set()
                if not pd.isna(raw_bridge):
                    neighbours = bridge_profiles[bridge_name].get(str(raw_bridge), set())

                if current_profile is None:
                    candidate_profiles = neighbours
                else:
                    candidate_profiles = {profile for profile in neighbours if profile != current_profile}

                bridge_prior_profiles[bridge_name] = len(candidate_profiles)
                supported = 0
                fraud_profiles: set[str] = set()
                max_rate = 0.0
                max_decay = 0.0

                for neighbour_profile in candidate_profiles:
                    history = histories["profile"].get(neighbour_profile)
                    confirmed, fraud, rate, _, decay = _history_snapshot(history, now)
                    if confirmed == 0:
                        continue
                    supported += 1
                    if fraud > 0:
                        fraud_profiles.add(neighbour_profile)
                        max_rate = max(max_rate, rate)
                        max_decay = max(max_decay, decay)

                bridge_supported_profiles[bridge_name] = supported
                bridge_fraud_profiles[bridge_name] = fraud_profiles
                bridge_max_rate[bridge_name] = max_rate
                bridge_max_decay[bridge_name] = max_decay
                if supported > 0:
                    two_hop_supported_channels += 1
                if fraud_profiles:
                    two_hop_fraud_channels += 1
                    union_fraud_profiles.update(fraud_profiles)

            # Aggregate unique two-hop fraud profiles once, even if corroborated
            # through multiple contextual bridges.
            two_hop_fraud_support = 0
            two_hop_fraud_30d = 0
            two_hop_max_rate = 0.0
            two_hop_max_decay = 0.0
            for neighbour_profile in union_fraud_profiles:
                history = histories["profile"].get(neighbour_profile)
                confirmed, fraud, rate, fraud_30d, decay = _history_snapshot(history, now)
                if confirmed == 0 or fraud == 0:
                    continue
                two_hop_fraud_support += fraud
                two_hop_fraud_30d += fraud_30d
                two_hop_max_rate = max(two_hop_max_rate, rate)
                two_hop_max_decay = max(two_hop_max_decay, decay)

            for bridge_name, prefix in (
                ("device_context", "device_bridge"),
                ("receiver_context", "receiver_bridge"),
            ):
                arrays[f"log_{prefix}_prior_profiles"][pos] = np.log1p(
                    bridge_prior_profiles.get(bridge_name, 0)
                )
                arrays[f"log_{prefix}_supported_profiles"][pos] = np.log1p(
                    bridge_supported_profiles.get(bridge_name, 0)
                )
                arrays[f"log_{prefix}_fraud_profiles"][pos] = np.log1p(
                    len(bridge_fraud_profiles.get(bridge_name, set()))
                )
                arrays[f"{prefix}_max_fraud_rate"][pos] = bridge_max_rate.get(bridge_name, 0.0)
                arrays[f"{prefix}_fraud_recency_decay"][pos] = bridge_max_decay.get(bridge_name, 0.0)

            arrays["two_hop_supported_channels"][pos] = two_hop_supported_channels
            arrays["two_hop_fraud_channels"][pos] = two_hop_fraud_channels
            arrays["log_two_hop_unique_fraud_profiles"][pos] = np.log1p(len(union_fraud_profiles))
            arrays["log_two_hop_confirmed_fraud_support"][pos] = np.log1p(two_hop_fraud_support)
            arrays["log_two_hop_confirmed_fraud_30d"][pos] = np.log1p(two_hop_fraud_30d)
            arrays["two_hop_max_fraud_rate"][pos] = two_hop_max_rate
            arrays["two_hop_fraud_recency_decay"][pos] = two_hop_max_decay
            arrays["two_hop_multi_profile_corroboration"][pos] = float(
                len(union_fraud_profiles) >= 2
            )

            # Confidence is structural evidence quality, not fraud likelihood.
            c = 0.10 * min(history_channels, 4)
            for name, weight in (
                ("device", 0.20),
                ("receiver", 0.20),
                ("profile", 0.10),
                ("device_context", 0.10),
            ):
                raw_key = direct_arrays[name][pos]
                if pd.isna(raw_key):
                    continue
                history = histories[name].get(str(raw_key))
                if history is not None and history.confirmed > 0:
                    c += weight
            c += 0.20 * min(np.log1p(total_support) / np.log1p(10.0), 1.0)
            # Two-hop support is deliberately weaker than direct support.
            c += 0.05 * min(two_hop_supported_channels, 2)
            c += 0.10 * min(two_hop_fraud_channels, 2)
            if len(union_fraud_profiles) >= 2:
                c += 0.10
            confidence[pos] = min(c, 1.0)

        # After the full timestamp batch is scored, update unlabeled adjacency and
        # enqueue eligible labels for delayed maturation.
        for pos in range(start, end):
            profile_raw = profile_array[pos]
            profile = None if pd.isna(profile_raw) else str(profile_raw)
            if profile is not None:
                for bridge_name in BRIDGE_KEYS:
                    raw_bridge = bridge_arrays[bridge_name][pos]
                    if not pd.isna(raw_bridge):
                        bridge_profiles[bridge_name][str(raw_bridge)].add(profile)

            if eligible_arr[pos]:
                stored_direct: dict[str, str | None] = {}
                for name in DIRECT_KEYS:
                    raw_key = direct_arrays[name][pos]
                    stored_direct[name] = None if pd.isna(raw_key) else str(raw_key)
                pending.append(
                    (now + LABEL_DELAY, now, int(labels[pos]), stored_direct)
                )

        start = end

    out = pd.DataFrame(arrays, index=original_index)
    out["feedback_confidence_v6"] = confidence
    return out.reindex(frame.index)


def feedback_matrix_v6(frame: pd.DataFrame) -> np.ndarray:
    missing = [feature for feature in FEEDBACK_FEATURES_V6 if feature not in frame.columns]
    if missing:
        raise KeyError(f"Missing v6 feedback features: {missing}")
    return frame[FEEDBACK_FEATURES_V6].to_numpy(dtype=np.float32, copy=False)


def fit_network_specialist_v6(
    raw: np.ndarray,
    relationship_features: pd.DataFrame,
    feedback_features: pd.DataFrame,
    labels: np.ndarray,
) -> XGBClassifier:
    confidence = feedback_features["feedback_confidence_v6"].to_numpy(dtype=float)
    active = confidence > 0.0
    x = np.hstack(
        [raw, relationship_matrix_v4(relationship_features), feedback_matrix_v6(feedback_features)]
    ).astype(np.float32, copy=False)
    y = np.asarray(labels, dtype=np.int8)
    ya = y[active]
    if active.sum() == 0 or len(np.unique(ya)) < 2:
        raise ValueError("Need feedback-active training rows from both classes")

    negatives = int((ya == 0).sum())
    positives = int((ya == 1).sum())
    model = XGBClassifier(
        objective="binary:logistic",
        eval_metric="aucpr",
        n_estimators=450,
        learning_rate=0.04,
        max_depth=5,
        min_child_weight=3,
        subsample=0.85,
        colsample_bytree=0.85,
        reg_lambda=1.5,
        reg_alpha=0.1,
        scale_pos_weight=negatives / max(positives, 1),
        tree_method="hist",
        max_bin=128,
        n_jobs=-1,
        random_state=42,
    )
    model.fit(x[active], ya, verbose=False)
    return model


def predict_network_specialist_v6(
    model: XGBClassifier,
    raw: np.ndarray,
    relationship_features: pd.DataFrame,
    feedback_features: pd.DataFrame,
) -> np.ndarray:
    x = np.hstack(
        [raw, relationship_matrix_v4(relationship_features), feedback_matrix_v6(feedback_features)]
    ).astype(np.float32, copy=False)
    return model.predict_proba(x)[:, 1]


def gate_network_scores(
    baseline: np.ndarray,
    specialist: np.ndarray,
    confidence: np.ndarray,
    strength: float,
) -> np.ndarray:
    baseline = np.asarray(baseline, dtype=float)
    specialist = np.asarray(specialist, dtype=float)
    confidence = np.asarray(confidence, dtype=float)
    if baseline.shape != specialist.shape or baseline.shape != confidence.shape:
        raise ValueError("baseline, specialist, and confidence must align")
    if not 0.0 <= strength <= 1.0:
        raise ValueError("strength must lie in [0, 1]")
    if np.any((confidence < 0.0) | (confidence > 1.0)):
        raise ValueError("confidence must lie in [0, 1]")
    fused = baseline + strength * confidence * (specialist - baseline)
    fallback = confidence == 0.0
    fused[fallback] = baseline[fallback]
    return np.clip(fused, 0.0, 1.0)


def v6_feedback_feature_importance(model: XGBClassifier) -> dict[str, float]:
    importances = np.asarray(model.feature_importances_, dtype=float)
    n_feedback = len(FEEDBACK_FEATURES_V6)
    if importances.size < n_feedback:
        return {}
    values = importances[-n_feedback:]
    return {
        feature: float(value)
        for feature, value in zip(FEEDBACK_FEATURES_V6, values)
    }
