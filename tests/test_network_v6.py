import numpy as np
import pandas as pd

from linkrisk.network_feedback_v6 import (
    LABEL_DELAY,
    build_network_feedback_v6,
    gate_network_scores,
)


def _row(time, amount, card1, device, browser, receiver, fraud):
    return {
        "TransactionDT": time,
        "TransactionAmt": amount,
        "card1": card1,
        "card2": 2,
        "card3": 3,
        "card5": 5,
        "addr1": 7,
        "DeviceInfo": device,
        "R_emaildomain": receiver,
        "id_31": browser,
        "isFraud": fraud,
    }


def test_v6_validation_labels_never_enter_memory_when_ineligible():
    frame = pd.DataFrame(
        [
            _row(0, 10.0, 1, "d1", "b1", "r1", 1),
            _row(LABEL_DELAY + 10, 20.0, 1, "d1", "b1", "r1", 0),
        ]
    )
    eligible = pd.Series(False, index=frame.index)
    features = build_network_feedback_v6(frame, eligible)

    assert features.loc[1, "profile_has_confirmed_fraud"] == 0.0
    assert features.loc[1, "confirmed_fraud_channels"] == 0.0


def test_v6_two_hop_fraud_propagates_only_after_delay_and_prior_adjacency():
    # Transaction 0 is an eligible confirmed fraud on profile A and device/browser X.
    # After the 72h delay, profile B arrives on the same device/browser context.
    # B has no direct profile history, but should see A as a two-hop fraud neighbour.
    frame = pd.DataFrame(
        [
            _row(0, 10.0, 1, "shared-device", "shared-browser", "r1", 1),
            _row(LABEL_DELAY - 1, 11.0, 9, "shared-device", "shared-browser", "r9", 0),
            _row(LABEL_DELAY + 1, 12.0, 8, "shared-device", "shared-browser", "r8", 0),
        ]
    )
    eligible = pd.Series([True, False, False], index=frame.index)
    features = build_network_feedback_v6(frame, eligible)

    assert features.loc[1, "two_hop_fraud_channels"] == 0.0
    assert features.loc[2, "two_hop_fraud_channels"] >= 1.0
    assert features.loc[2, "log_two_hop_unique_fraud_profiles"] > 0.0


def test_v6_same_timestamp_rows_do_not_create_adjacency_for_each_other():
    frame = pd.DataFrame(
        [
            _row(0, 10.0, 1, "d", "b", "r1", 0),
            _row(0, 20.0, 2, "d", "b", "r2", 0),
        ]
    )
    eligible = pd.Series(False, index=frame.index)
    features = build_network_feedback_v6(frame, eligible)

    assert features.loc[0, "log_device_bridge_prior_profiles"] == 0.0
    assert features.loc[1, "log_device_bridge_prior_profiles"] == 0.0


def test_v6_gate_exact_fallback():
    baseline = np.array([0.2, 0.8, 0.4])
    specialist = np.array([0.9, 0.3, 0.7])
    confidence = np.array([0.0, 0.5, 1.0])

    fused = gate_network_scores(baseline, specialist, confidence, 1.0)

    assert fused[0] == baseline[0]
    assert np.isclose(fused[1], 0.55)
    assert fused[2] == specialist[2]
