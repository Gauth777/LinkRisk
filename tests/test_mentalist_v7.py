import numpy as np
import pandas as pd
import pandas.testing as pdt

from linkrisk.mentalist_features_v7 import (
    build_coordination_motifs_v7,
    build_mentalist_features_v7,
    calibrate_clue_thresholds,
    clue_activations,
)


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "TransactionDT": [0.0, 100.0, 100.0, 200.0],
            "TransactionAmt": [100.0, 110.0, 120.0, 130.0],
            "card1": [1001, 1002, 1003, 1004],
            "card2": [200, 201, 202, 203],
            "card3": [150, 150, 150, 150],
            "card5": [226, 226, 226, 226],
            "addr1": [300, 301, 302, 303],
            "R_emaildomain": ["merchant.test"] * 4,
            "DeviceInfo": ["shared-device"] * 4,
            "id_31": ["shared-browser"] * 4,
        }
    )


def test_same_timestamp_rows_do_not_see_each_other():
    motifs = build_coordination_motifs_v7(_frame())

    # Both t=100 rows can see only the t=0 profile, never one another.
    expected_one = np.log1p(1)
    assert np.isclose(motifs.loc[1, "log_context_tx_10m"], expected_one)
    assert np.isclose(motifs.loc[2, "log_context_tx_10m"], expected_one)
    assert np.isclose(
        motifs.loc[1, "log_context_unique_profiles_10m"], expected_one
    )
    assert np.isclose(
        motifs.loc[2, "log_context_unique_profiles_10m"], expected_one
    )

    # The later row sees all three genuinely prior profiles.
    assert np.isclose(motifs.loc[3, "log_context_tx_10m"], np.log1p(3))
    assert np.isclose(
        motifs.loc[3, "log_context_unique_profiles_10m"], np.log1p(3)
    )


def test_future_rows_cannot_change_prior_mentalist_features():
    frame = _frame()
    prefix = frame.iloc[:3].copy()

    before = build_mentalist_features_v7(prefix)
    after = build_mentalist_features_v7(frame).loc[prefix.index]
    pdt.assert_frame_equal(before, after)


def test_mentalist_feature_builder_requires_no_fraud_target():
    frame = _frame()
    assert "isFraud" not in frame.columns
    features = build_mentalist_features_v7(frame)
    assert len(features) == len(frame)
    assert np.isfinite(features.to_numpy()).all()


def test_clue_thresholds_are_calibrated_from_legitimate_training_rows():
    frame = _frame()
    features = build_mentalist_features_v7(frame)
    labels = np.array([0, 0, 0, 1], dtype=np.int8)

    thresholds = calibrate_clue_thresholds(features, labels, quantile=0.90)
    clues = clue_activations(features, thresholds)

    assert set(clues["independent_clue_count"].unique()).issubset({0, 1, 2, 3, 4})
    assert all(name.startswith("clue_") or name == "independent_clue_count" for name in clues.columns)
