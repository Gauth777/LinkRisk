import pandas as pd

from linkrisk.feedback_features_v5 import (
    LABEL_DELAY_SECONDS,
    build_feedback_features_v5,
)


def _row(tx_id: str, timestamp: float, label: int) -> dict:
    return {
        "TransactionID": tx_id,
        "TransactionDT": timestamp,
        "isFraud": label,
        "card1": 1111,
        "card2": 222,
        "card3": 150,
        "card5": 226,
        "addr1": 315,
        "DeviceInfo": "device-A",
        "R_emaildomain": "gmail.com",
        "id_31": "chrome 63.0",
    }


def test_confirmed_fraud_is_invisible_until_fixed_delay():
    frame = pd.DataFrame(
        [
            _row("A", 0.0, 1),
            _row("B", LABEL_DELAY_SECONDS - 1, 0),
            _row("C", LABEL_DELAY_SECONDS, 0),
        ]
    ).set_index("TransactionID", drop=False)
    eligible = pd.Series({"A": True, "B": False, "C": False})

    feedback = build_feedback_features_v5(frame, eligible)

    assert feedback.loc["B", "feedback_confidence"] == 0.0
    assert feedback.loc["B", "confirmed_fraud_channels"] == 0.0
    assert feedback.loc["C", "confirmed_fraud_channels"] == 4.0
    assert feedback.loc["C", "any_strong_confirmed_fraud"] == 1.0
    assert feedback.loc["C", "feedback_confidence"] == 1.0


def test_unadjudicated_history_never_enters_feedback_memory():
    frame = pd.DataFrame(
        [
            _row("A", 0.0, 1),
            _row("B", LABEL_DELAY_SECONDS + 10, 0),
        ]
    ).set_index("TransactionID", drop=False)
    eligible = pd.Series(False, index=frame.index)

    feedback = build_feedback_features_v5(frame, eligible)

    assert feedback.loc["B", "feedback_history_channels"] == 0.0
    assert feedback.loc["B", "confirmed_fraud_channels"] == 0.0
    assert feedback.loc["B", "feedback_confidence"] == 0.0
