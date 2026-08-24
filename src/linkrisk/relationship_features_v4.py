from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Deque

import numpy as np
import pandas as pd


TIME_COL = "TransactionDT"
WINDOW_10M = 10 * 60
WINDOW_1H = 60 * 60
WINDOW_24H = 24 * 60 * 60

PAYMENT_PROFILE_COLUMNS = ["card1", "card2", "card3", "card5", "addr1"]
STRONG_DEVICE_COLUMNS = ["card1", "addr1", "DeviceInfo"]
STRONG_RECEIVER_COLUMNS = ["card1", "addr1", "R_emaildomain"]
DEVICE_CONTEXT_COLUMNS = ["DeviceInfo", "id_31"]

RELATIONSHIP_FEATURES_V4 = [
    "log_profile_prior_total",
    "log_profile_prior_10m",
    "log_profile_prior_1h",
    "log_profile_prior_24h",
    "log_seconds_since_profile_last",
    "profile_velocity_1h_share",
    "profile_acceleration_10m_vs_1h",
    "profile_amount_history_available",
    "profile_amount_signed_log_ratio",
    "profile_amount_abs_log_ratio",
    "profile_amount_zscore",
    "log_profile_unique_deviceinfo_prior",
    "log_profile_unique_rdomain_prior",
    "log_profile_unique_browser_prior",
    "known_profile_new_deviceinfo",
    "known_profile_new_r_emaildomain",
    "known_profile_new_browser",
    "log_strong_device_prior_total",
    "log_strong_device_prior_1h",
    "log_strong_device_prior_24h",
    "log_strong_receiver_prior_total",
    "log_strong_receiver_prior_1h",
    "log_strong_receiver_prior_24h",
    "strong_active_count",
    "log_device_context_prior_profiles",
    "device_context_new_profile",
]


@dataclass
class ProfileHistory:
    recent_10m: Deque[float] = field(default_factory=deque)
    recent_1h: Deque[float] = field(default_factory=deque)
    recent_24h: Deque[float] = field(default_factory=deque)
    total_seen: int = 0
    last_seen: float | None = None
    amount_count: int = 0
    amount_sum: float = 0.0
    amount_sum_sq: float = 0.0
    deviceinfos: set[str] = field(default_factory=set)
    rdomains: set[str] = field(default_factory=set)
    browsers: set[str] = field(default_factory=set)


@dataclass
class SimpleHistory:
    recent_1h: Deque[float] = field(default_factory=deque)
    recent_24h: Deque[float] = field(default_factory=deque)
    total_seen: int = 0
    last_seen: float | None = None


def make_composite_key(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise KeyError(f"Missing columns for relationship key: {missing}")

    complete = frame[columns].notna().all(axis=1)
    result = pd.Series(pd.NA, index=frame.index, dtype="string")
    if not complete.any():
        return result

    encoded = frame.loc[complete, columns].astype("string")
    combined = pd.Series("", index=encoded.index, dtype="string")
    for idx, column in enumerate(columns):
        part = column + "=" + encoded[column]
        combined = part if idx == 0 else combined + "|" + part
    result.loc[complete] = combined
    return result


def _prune(queue: Deque[float], cutoff: float) -> None:
    while queue and queue[0] < cutoff:
        queue.popleft()


def _profile_snapshot(history: ProfileHistory | None, timestamp: float) -> dict[str, float]:
    if history is None:
        return {
            "total": 0,
            "prior_10m": 0,
            "prior_1h": 0,
            "prior_24h": 0,
            "seconds_since_last": np.nan,
            "amount_count": 0,
            "amount_mean": np.nan,
            "amount_std": np.nan,
            "unique_deviceinfo": 0,
            "unique_rdomain": 0,
            "unique_browser": 0,
        }

    _prune(history.recent_10m, timestamp - WINDOW_10M)
    _prune(history.recent_1h, timestamp - WINDOW_1H)
    _prune(history.recent_24h, timestamp - WINDOW_24H)

    amount_mean = (
        history.amount_sum / history.amount_count
        if history.amount_count
        else np.nan
    )
    if history.amount_count >= 2:
        variance = max(
            history.amount_sum_sq / history.amount_count - amount_mean * amount_mean,
            0.0,
        )
        amount_std = float(np.sqrt(variance))
    else:
        amount_std = np.nan

    return {
        "total": history.total_seen,
        "prior_10m": len(history.recent_10m),
        "prior_1h": len(history.recent_1h),
        "prior_24h": len(history.recent_24h),
        "seconds_since_last": (
            timestamp - history.last_seen if history.last_seen is not None else np.nan
        ),
        "amount_count": history.amount_count,
        "amount_mean": amount_mean,
        "amount_std": amount_std,
        "unique_deviceinfo": len(history.deviceinfos),
        "unique_rdomain": len(history.rdomains),
        "unique_browser": len(history.browsers),
    }


def _simple_snapshot(history: SimpleHistory | None, timestamp: float) -> tuple[int, int, int, float]:
    if history is None:
        return 0, 0, 0, np.nan
    _prune(history.recent_1h, timestamp - WINDOW_1H)
    _prune(history.recent_24h, timestamp - WINDOW_24H)
    return (
        history.total_seen,
        len(history.recent_1h),
        len(history.recent_24h),
        timestamp - history.last_seen if history.last_seen is not None else np.nan,
    )


def build_relationship_features_v4(frame: pd.DataFrame) -> pd.DataFrame:
    """Build richer causal relationship features for the graph-aware expert.

    All features use only transactions with TransactionDT strictly smaller than
    the current transaction. Rows sharing an exact timestamp are scored first
    and inserted into history only after the whole timestamp batch is scored.
    """
    required = {
        TIME_COL,
        "TransactionAmt",
        *PAYMENT_PROFILE_COLUMNS,
        *STRONG_DEVICE_COLUMNS,
        *STRONG_RECEIVER_COLUMNS,
        *DEVICE_CONTEXT_COLUMNS,
        "R_emaildomain",
        "DeviceInfo",
        "id_31",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise KeyError(f"Missing columns required for v4 relationship features: {missing}")

    working = frame.copy()
    working["_payment_profile"] = make_composite_key(working, PAYMENT_PROFILE_COLUMNS)
    working["_strong_device"] = make_composite_key(working, STRONG_DEVICE_COLUMNS)
    working["_strong_receiver"] = make_composite_key(working, STRONG_RECEIVER_COLUMNS)
    working["_device_context"] = make_composite_key(working, DEVICE_CONTEXT_COLUMNS)
    working = working.sort_values(TIME_COL, kind="mergesort")

    n = len(working)
    original_index = working.index.to_numpy()
    timestamps = working[TIME_COL].to_numpy(dtype=float)
    amounts = pd.to_numeric(working["TransactionAmt"], errors="coerce").to_numpy(dtype=float)
    profile_keys = working["_payment_profile"].astype("object").to_numpy()
    device_keys = working["_strong_device"].astype("object").to_numpy()
    receiver_keys = working["_strong_receiver"].astype("object").to_numpy()
    device_context_keys = working["_device_context"].astype("object").to_numpy()
    deviceinfo_values = working["DeviceInfo"].astype("object").to_numpy()
    rdomain_values = working["R_emaildomain"].astype("object").to_numpy()
    browser_values = working["id_31"].astype("object").to_numpy()

    profile_histories: dict[str, ProfileHistory] = defaultdict(ProfileHistory)
    strong_device_histories: dict[str, SimpleHistory] = defaultdict(SimpleHistory)
    strong_receiver_histories: dict[str, SimpleHistory] = defaultdict(SimpleHistory)
    device_context_profiles: dict[str, set[str]] = defaultdict(set)

    arrays = {
        name: np.zeros(n, dtype=np.float32)
        for name in RELATIONSHIP_FEATURES_V4
    }
    confidence = np.zeros(n, dtype=np.float32)

    start = 0
    while start < n:
        timestamp = float(timestamps[start])
        end = start + 1
        while end < n and timestamps[end] == timestamp:
            end += 1

        for pos in range(start, end):
            profile_key = profile_keys[pos]
            strong_device_key = device_keys[pos]
            strong_receiver_key = receiver_keys[pos]
            device_context_key = device_context_keys[pos]
            amount = amounts[pos]

            profile_history = None
            profile_stats = _profile_snapshot(None, timestamp)
            if not pd.isna(profile_key):
                profile_history = profile_histories.get(str(profile_key))
                profile_stats = _profile_snapshot(profile_history, timestamp)

            total = int(profile_stats["total"])
            prior_10m = int(profile_stats["prior_10m"])
            prior_1h = int(profile_stats["prior_1h"])
            prior_24h = int(profile_stats["prior_24h"])
            arrays["log_profile_prior_total"][pos] = np.log1p(total)
            arrays["log_profile_prior_10m"][pos] = np.log1p(prior_10m)
            arrays["log_profile_prior_1h"][pos] = np.log1p(prior_1h)
            arrays["log_profile_prior_24h"][pos] = np.log1p(prior_24h)

            since_last = profile_stats["seconds_since_last"]
            arrays["log_seconds_since_profile_last"][pos] = (
                np.log1p(since_last) if np.isfinite(since_last) else 0.0
            )
            arrays["profile_velocity_1h_share"][pos] = (
                prior_1h / max(prior_24h, 1)
            )
            arrays["profile_acceleration_10m_vs_1h"][pos] = (
                (6.0 * prior_10m) / max(prior_1h, 1)
            )

            amount_count = int(profile_stats["amount_count"])
            amount_mean = float(profile_stats["amount_mean"])
            amount_std = float(profile_stats["amount_std"])
            if amount_count >= 1 and np.isfinite(amount) and np.isfinite(amount_mean):
                arrays["profile_amount_history_available"][pos] = 1.0
                signed_log_ratio = np.log1p(max(amount, 0.0)) - np.log1p(max(amount_mean, 0.0))
                arrays["profile_amount_signed_log_ratio"][pos] = signed_log_ratio
                arrays["profile_amount_abs_log_ratio"][pos] = abs(signed_log_ratio)
                if amount_count >= 2 and np.isfinite(amount_std) and amount_std > 1e-6:
                    arrays["profile_amount_zscore"][pos] = np.clip(
                        (amount - amount_mean) / amount_std,
                        -10.0,
                        10.0,
                    )

            unique_device = int(profile_stats["unique_deviceinfo"])
            unique_rdomain = int(profile_stats["unique_rdomain"])
            unique_browser = int(profile_stats["unique_browser"])
            arrays["log_profile_unique_deviceinfo_prior"][pos] = np.log1p(unique_device)
            arrays["log_profile_unique_rdomain_prior"][pos] = np.log1p(unique_rdomain)
            arrays["log_profile_unique_browser_prior"][pos] = np.log1p(unique_browser)

            device_value = deviceinfo_values[pos]
            rdomain_value = rdomain_values[pos]
            browser_value = browser_values[pos]
            known_profile = total > 0

            device_comparable = known_profile and not pd.isna(device_value)
            rdomain_comparable = known_profile and not pd.isna(rdomain_value)
            browser_comparable = known_profile and not pd.isna(browser_value)

            if device_comparable:
                arrays["known_profile_new_deviceinfo"][pos] = float(
                    profile_history is not None
                    and str(device_value) not in profile_history.deviceinfos
                )
            if rdomain_comparable:
                arrays["known_profile_new_r_emaildomain"][pos] = float(
                    profile_history is not None
                    and str(rdomain_value) not in profile_history.rdomains
                )
            if browser_comparable:
                arrays["known_profile_new_browser"][pos] = float(
                    profile_history is not None
                    and str(browser_value) not in profile_history.browsers
                )

            d_total, d_1h, d_24h, _ = _simple_snapshot(
                strong_device_histories.get(str(strong_device_key))
                if not pd.isna(strong_device_key)
                else None,
                timestamp,
            )
            r_total, r_1h, r_24h, _ = _simple_snapshot(
                strong_receiver_histories.get(str(strong_receiver_key))
                if not pd.isna(strong_receiver_key)
                else None,
                timestamp,
            )
            arrays["log_strong_device_prior_total"][pos] = np.log1p(d_total)
            arrays["log_strong_device_prior_1h"][pos] = np.log1p(d_1h)
            arrays["log_strong_device_prior_24h"][pos] = np.log1p(d_24h)
            arrays["log_strong_receiver_prior_total"][pos] = np.log1p(r_total)
            arrays["log_strong_receiver_prior_1h"][pos] = np.log1p(r_1h)
            arrays["log_strong_receiver_prior_24h"][pos] = np.log1p(r_24h)
            arrays["strong_active_count"][pos] = float((d_24h > 0) + (r_24h > 0))

            prior_profiles_for_device = 0
            device_context_new_profile = 0.0
            if not pd.isna(device_context_key):
                seen_profiles = device_context_profiles.get(str(device_context_key))
                prior_profiles_for_device = len(seen_profiles) if seen_profiles else 0
                if (
                    seen_profiles
                    and not pd.isna(profile_key)
                    and str(profile_key) not in seen_profiles
                ):
                    device_context_new_profile = 1.0
            arrays["log_device_context_prior_profiles"][pos] = np.log1p(prior_profiles_for_device)
            arrays["device_context_new_profile"][pos] = device_context_new_profile

            c = 0.0
            if prior_24h > 0:
                c += 0.25
            if amount_count >= 3:
                c += 0.10
            if device_comparable:
                c += 0.10
            if rdomain_comparable:
                c += 0.10
            if browser_comparable:
                c += 0.05
            if d_24h > 0:
                c += 0.15
            if r_24h > 0:
                c += 0.15
            if prior_profiles_for_device > 0:
                c += 0.10
            confidence[pos] = min(c, 1.0)

        # Update histories only after all rows at this timestamp were scored.
        for pos in range(start, end):
            profile_key = profile_keys[pos]
            strong_device_key = device_keys[pos]
            strong_receiver_key = receiver_keys[pos]
            device_context_key = device_context_keys[pos]
            amount = amounts[pos]

            if not pd.isna(profile_key):
                profile_string = str(profile_key)
                history = profile_histories[profile_string]
                _prune(history.recent_10m, timestamp - WINDOW_10M)
                _prune(history.recent_1h, timestamp - WINDOW_1H)
                _prune(history.recent_24h, timestamp - WINDOW_24H)
                history.recent_10m.append(timestamp)
                history.recent_1h.append(timestamp)
                history.recent_24h.append(timestamp)
                history.total_seen += 1
                history.last_seen = timestamp
                if np.isfinite(amount):
                    history.amount_count += 1
                    history.amount_sum += float(amount)
                    history.amount_sum_sq += float(amount) * float(amount)
                if not pd.isna(deviceinfo_values[pos]):
                    history.deviceinfos.add(str(deviceinfo_values[pos]))
                if not pd.isna(rdomain_values[pos]):
                    history.rdomains.add(str(rdomain_values[pos]))
                if not pd.isna(browser_values[pos]):
                    history.browsers.add(str(browser_values[pos]))

            if not pd.isna(strong_device_key):
                history = strong_device_histories[str(strong_device_key)]
                _prune(history.recent_1h, timestamp - WINDOW_1H)
                _prune(history.recent_24h, timestamp - WINDOW_24H)
                history.recent_1h.append(timestamp)
                history.recent_24h.append(timestamp)
                history.total_seen += 1
                history.last_seen = timestamp

            if not pd.isna(strong_receiver_key):
                history = strong_receiver_histories[str(strong_receiver_key)]
                _prune(history.recent_1h, timestamp - WINDOW_1H)
                _prune(history.recent_24h, timestamp - WINDOW_24H)
                history.recent_1h.append(timestamp)
                history.recent_24h.append(timestamp)
                history.total_seen += 1
                history.last_seen = timestamp

            if not pd.isna(device_context_key) and not pd.isna(profile_key):
                device_context_profiles[str(device_context_key)].add(str(profile_key))

        start = end

    out = pd.DataFrame(arrays, index=original_index)
    out["graph_confidence_v4"] = confidence
    return out.reindex(frame.index)


def relationship_matrix_v4(features: pd.DataFrame) -> np.ndarray:
    missing = [name for name in RELATIONSHIP_FEATURES_V4 if name not in features.columns]
    if missing:
        raise KeyError(f"Missing v4 relationship features: {missing}")
    values = features[RELATIONSHIP_FEATURES_V4].to_numpy(dtype=np.float32)
    values[~np.isfinite(values)] = 0.0
    return values
