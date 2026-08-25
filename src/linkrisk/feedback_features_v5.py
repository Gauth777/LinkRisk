from __future__ import annotations

from collections import defaultdict, deque

import numpy as np
import pandas as pd

from linkrisk.baseline import TARGET, TIME_COL
from linkrisk.feedback_schema import FEEDBACK_CONFIDENCE_COLUMN, FEEDBACK_FEATURES_V5
from linkrisk.relationship_features_v4 import (
    DEVICE_CONTEXT_COLUMNS,
    PAYMENT_PROFILE_COLUMNS,
    STRONG_DEVICE_COLUMNS,
    STRONG_RECEIVER_COLUMNS,
    make_composite_key,
)


LABEL_DELAY_SECONDS = 72 * 60 * 60
WINDOW_30D_SECONDS = 30 * 24 * 60 * 60

FEEDBACK_KEYS_V5 = {
    "profile": PAYMENT_PROFILE_COLUMNS,
    "device": STRONG_DEVICE_COLUMNS,
    "receiver": STRONG_RECEIVER_COLUMNS,
    "device_context": DEVICE_CONTEXT_COLUMNS,
}


class _History:
    __slots__ = ("confirmed", "fraud", "fraud_times")

    def __init__(self) -> None:
        self.confirmed = 0
        self.fraud = 0
        self.fraud_times = deque()


def build_feedback_features_v5(
    frame: pd.DataFrame,
    label_eligible: pd.Series,
) -> pd.DataFrame:
    """Build the frozen v0.5 delayed-feedback features.

    This mirrors the champion experiment. A historical outcome is eligible only
    when the caller explicitly marks it adjudicated, and even then it cannot
    enter relationship memory before transaction_time + 72 hours. Current or
    unadjudicated labels must therefore be passed with eligibility=False.
    """
    required = {TARGET, TIME_COL}
    for columns in FEEDBACK_KEYS_V5.values():
        required.update(columns)
    missing = sorted(required - set(frame.columns))
    if missing:
        raise KeyError(f"Missing columns required for v0.5 feedback features: {missing}")

    working = frame.copy()
    eligible = label_eligible.reindex(working.index).fillna(False).astype(bool)
    working["_eligible"] = eligible
    for name, columns in FEEDBACK_KEYS_V5.items():
        working[f"_key_{name}"] = make_composite_key(working, columns)

    working = working.sort_values(TIME_COL, kind="mergesort")
    original_index = working.index.to_numpy()
    times = working[TIME_COL].to_numpy(dtype=float)
    labels = working[TARGET].astype(np.int8).to_numpy()
    eligible_arr = working["_eligible"].to_numpy(dtype=bool)
    keys = {
        name: working[f"_key_{name}"].astype("object").to_numpy()
        for name in FEEDBACK_KEYS_V5
    }

    histories = {name: defaultdict(_History) for name in FEEDBACK_KEYS_V5}
    pending = deque()
    arrays = {
        name: np.zeros(len(working), dtype=np.float32)
        for name in FEEDBACK_FEATURES_V5
    }
    confidence = np.zeros(len(working), dtype=np.float32)

    start = 0
    while start < len(working):
        now = float(times[start])
        end = start + 1
        while end < len(working) and times[end] == now:
            end += 1

        while pending and pending[0][0] <= now:
            _, original_time, label, stored_keys = pending.popleft()
            for name, key in stored_keys.items():
                if key is None:
                    continue
                history = histories[name][key]
                history.confirmed += 1
                if label == 1:
                    history.fraud += 1
                    history.fraud_times.append(original_time)

        for pos in range(start, end):
            history_channels = 0
            fraud_channels = 0
            total_support = 0
            max_rate = 0.0
            strong_fraud = 0.0

            for name in FEEDBACK_KEYS_V5:
                raw_key = keys[name][pos]
                if pd.isna(raw_key):
                    continue
                history = histories[name].get(str(raw_key))
                if history is None or history.confirmed == 0:
                    continue

                cutoff = now - WINDOW_30D_SECONDS
                while history.fraud_times and history.fraud_times[0] < cutoff:
                    history.fraud_times.popleft()

                rate = history.fraud / history.confirmed
                arrays[f"log_{name}_confirmed_total"][pos] = np.log1p(history.confirmed)
                arrays[f"log_{name}_confirmed_fraud_total"][pos] = np.log1p(history.fraud)
                arrays[f"{name}_confirmed_fraud_rate"][pos] = rate
                arrays[f"log_{name}_confirmed_fraud_30d"][pos] = np.log1p(
                    len(history.fraud_times)
                )
                arrays[f"{name}_has_confirmed_fraud"][pos] = float(history.fraud > 0)

                history_channels += 1
                total_support += history.confirmed
                max_rate = max(max_rate, rate)
                if history.fraud > 0:
                    fraud_channels += 1
                    if name in {"device", "receiver"}:
                        strong_fraud = 1.0

            arrays["feedback_history_channels"][pos] = history_channels
            arrays["confirmed_fraud_channels"][pos] = fraud_channels
            arrays["any_strong_confirmed_fraud"][pos] = strong_fraud
            arrays["max_confirmed_fraud_rate"][pos] = max_rate
            arrays["feedback_total_support_log"][pos] = np.log1p(total_support)

            # Confidence measures support quality, not fraud probability.
            c = 0.10 * min(history_channels, 4)
            for name, weight in (
                ("device", 0.20),
                ("receiver", 0.20),
                ("profile", 0.10),
                ("device_context", 0.10),
            ):
                raw_key = keys[name][pos]
                if pd.isna(raw_key):
                    continue
                history = histories[name].get(str(raw_key))
                if history is not None and history.confirmed > 0:
                    c += weight

            c += 0.20 * min(
                np.log1p(total_support) / np.log1p(10.0),
                1.0,
            )
            confidence[pos] = min(c, 1.0)

        # Same-timestamp rows are scored before any label at that timestamp can
        # be queued. Eligible outcomes become visible only after 72 hours.
        for pos in range(start, end):
            if not eligible_arr[pos]:
                continue
            stored_keys = {}
            for name in FEEDBACK_KEYS_V5:
                raw_key = keys[name][pos]
                stored_keys[name] = None if pd.isna(raw_key) else str(raw_key)
            pending.append(
                (
                    now + LABEL_DELAY_SECONDS,
                    now,
                    int(labels[pos]),
                    stored_keys,
                )
            )

        start = end

    out = pd.DataFrame(arrays, index=original_index)
    out[FEEDBACK_CONFIDENCE_COLUMN] = confidence
    return out.reindex(frame.index)
