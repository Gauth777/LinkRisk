from __future__ import annotations

import numpy as np
import pandas as pd


FEEDBACK_CHANNELS_V5 = (
    "profile",
    "device",
    "receiver",
    "device_context",
)

FEEDBACK_FEATURES_V5: list[str] = []
for channel in FEEDBACK_CHANNELS_V5:
    FEEDBACK_FEATURES_V5 += [
        f"log_{channel}_confirmed_total",
        f"log_{channel}_confirmed_fraud_total",
        f"{channel}_confirmed_fraud_rate",
        f"log_{channel}_confirmed_fraud_30d",
        f"{channel}_has_confirmed_fraud",
    ]

FEEDBACK_FEATURES_V5 += [
    "feedback_history_channels",
    "confirmed_fraud_channels",
    "any_strong_confirmed_fraud",
    "max_confirmed_fraud_rate",
    "feedback_total_support_log",
]

FEEDBACK_CONFIDENCE_COLUMN = "feedback_confidence"


def feedback_matrix_v5(frame: pd.DataFrame) -> np.ndarray:
    """Return v0.5 feedback features in the exact specialist-training order."""
    missing = [column for column in FEEDBACK_FEATURES_V5 if column not in frame.columns]
    if missing:
        raise KeyError(f"Missing v0.5 feedback features: {missing}")
    return frame[FEEDBACK_FEATURES_V5].to_numpy(dtype=np.float32, copy=False)
