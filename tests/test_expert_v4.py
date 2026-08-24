import numpy as np
import pandas as pd

from linkrisk.expert_v4 import confidence_gate_expert
from linkrisk.relationship_features_v4 import build_relationship_features_v4


def test_v4_same_timestamp_rows_do_not_see_each_other():
    frame = pd.DataFrame(
        {
            "TransactionDT": [1000, 1000, 2000],
            "TransactionAmt": [10.0, 20.0, 30.0],
            "card1": [1, 1, 1],
            "card2": [2, 2, 2],
            "card3": [3, 3, 3],
            "card5": [5, 5, 5],
            "addr1": [7, 7, 7],
            "DeviceInfo": ["d", "d", "d"],
            "R_emaildomain": ["r", "r", "r"],
            "id_31": ["b", "b", "b"],
        }
    )

    features = build_relationship_features_v4(frame)

    assert features.loc[0, "log_profile_prior_total"] == 0.0
    assert features.loc[1, "log_profile_prior_total"] == 0.0
    assert np.isclose(features.loc[2, "log_profile_prior_total"], np.log1p(2))


def test_v4_confidence_gate_exact_fallback():
    baseline = np.array([0.1, 0.8, 0.4])
    expert = np.array([0.9, 0.2, 0.7])
    confidence = np.array([0.0, 0.5, 1.0])

    fused = confidence_gate_expert(baseline, expert, confidence, gate_strength=1.0)

    assert fused[0] == baseline[0]
    assert np.isclose(fused[1], 0.5)
    assert fused[2] == expert[2]
