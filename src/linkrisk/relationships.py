from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque

import numpy as np
import pandas as pd


TIME_COL = "TransactionDT"

RELATIONSHIP_KEYS = {
    "payment_device_profile": ["card1", "addr1", "DeviceInfo"],
    "payment_receiver_profile": ["card1", "addr1", "R_emaildomain"],
}

WINDOW_1H = 60 * 60
WINDOW_24H = 24 * 60 * 60


@dataclass
class KeyHistory:
    recent_24h: Deque[float]
    total_seen: int = 0
    last_seen: float | None = None


def _empty_history() -> KeyHistory:
    return KeyHistory(recent_24h=deque())


def make_composite_key(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    """Create a pseudo-entity key only when every required field is present."""
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise KeyError(f"Missing columns for relationship key: {missing}")

    complete = frame[columns].notna().all(axis=1)
    result = pd.Series(pd.NA, index=frame.index, dtype="string")
    if not complete.any():
        return result

    encoded = frame.loc[complete, columns].astype("string")
    combined = pd.Series("", index=encoded.index, dtype="string")
    for index, column in enumerate(columns):
        part = column + "=" + encoded[column]
        combined = part if index == 0 else combined + "|" + part

    result.loc[complete] = combined
    return result


def add_relationship_keys(frame: pd.DataFrame) -> pd.DataFrame:
    enriched = frame.copy()
    for name, columns in RELATIONSHIP_KEYS.items():
        enriched[name] = make_composite_key(enriched, columns)
    return enriched


def _snapshot(history: KeyHistory | None, timestamp: float) -> tuple[int, int, int, float]:
    """
    Return total prior count, prior 1h count, prior 24h count, seconds since last.

    The caller must pass history containing only events strictly earlier than
    timestamp. This function mutates only by pruning events older than 24h.
    """
    if history is None:
        return 0, 0, 0, np.nan

    cutoff_24h = timestamp - WINDOW_24H
    while history.recent_24h and history.recent_24h[0] < cutoff_24h:
        history.recent_24h.popleft()

    prior_24h = len(history.recent_24h)
    cutoff_1h = timestamp - WINDOW_1H
    prior_1h = sum(value >= cutoff_1h for value in history.recent_24h)
    seconds_since_last = (
        timestamp - history.last_seen
        if history.last_seen is not None
        else np.nan
    )

    return history.total_seen, prior_1h, prior_24h, seconds_since_last


def build_temporal_relationship_features(frame: pd.DataFrame) -> pd.DataFrame:
    """
    Build leakage-safe temporal relationship features in one chronological pass.

    Critical invariant: rows sharing the same TransactionDT are scored as a
    batch before any of them are inserted into history. Therefore only events
    with strictly smaller timestamps can influence the current row.
    """
    if TIME_COL not in frame.columns:
        raise KeyError(f"{TIME_COL} is required")

    working = add_relationship_keys(frame)
    working = working.sort_values(TIME_COL, kind="mergesort").copy()

    histories: dict[str, dict[str, KeyHistory]] = {
        name: defaultdict(_empty_history) for name in RELATIONSHIP_KEYS
    }

    output = pd.DataFrame(index=working.index)

    for name in RELATIONSHIP_KEYS:
        output[f"{name}_available"] = 0
        output[f"{name}_prior_total"] = 0
        output[f"{name}_prior_1h"] = 0
        output[f"{name}_prior_24h"] = 0
        output[f"{name}_seconds_since_last"] = np.nan

    # Grouping by exact timestamp prevents same-time rows from seeing each other.
    for timestamp, batch in working.groupby(TIME_COL, sort=False):
        timestamp = float(timestamp)

        # 1) Read prior state and compute features.
        for row_index, row in batch.iterrows():
            for name in RELATIONSHIP_KEYS:
                key = row[name]
                if pd.isna(key):
                    continue

                output.at[row_index, f"{name}_available"] = 1
                history = histories[name].get(str(key))
                total, prior_1h, prior_24h, since_last = _snapshot(
                    history,
                    timestamp,
                )
                output.at[row_index, f"{name}_prior_total"] = total
                output.at[row_index, f"{name}_prior_1h"] = prior_1h
                output.at[row_index, f"{name}_prior_24h"] = prior_24h
                output.at[row_index, f"{name}_seconds_since_last"] = since_last

        # 2) Only after every row at this timestamp is scored, update history.
        for _, row in batch.iterrows():
            for name in RELATIONSHIP_KEYS:
                key = row[name]
                if pd.isna(key):
                    continue

                history = histories[name][str(key)]
                cutoff_24h = timestamp - WINDOW_24H
                while history.recent_24h and history.recent_24h[0] < cutoff_24h:
                    history.recent_24h.popleft()

                history.recent_24h.append(timestamp)
                history.total_seen += 1
                history.last_seen = timestamp

    available_cols = [f"{name}_available" for name in RELATIONSHIP_KEYS]
    prior_cols = [f"{name}_prior_24h" for name in RELATIONSHIP_KEYS]
    prior_1h_cols = [f"{name}_prior_1h" for name in RELATIONSHIP_KEYS]

    output["graph_key_coverage"] = output[available_cols].sum(axis=1) / len(available_cols)
    output["graph_active_prior_keys"] = (output[prior_cols] > 0).sum(axis=1)
    output["graph_prior_1h_max"] = output[prior_1h_cols].max(axis=1)
    output["graph_prior_24h_max"] = output[prior_cols].max(axis=1)
    output["graph_multi_key_prior"] = (output["graph_active_prior_keys"] >= 2).astype(int)

    return output.reindex(frame.index)
