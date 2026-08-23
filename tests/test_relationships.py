import pandas as pd

from linkrisk.relationships import build_temporal_relationship_features


def test_same_timestamp_rows_do_not_see_each_other():
    frame = pd.DataFrame(
        {
            "TransactionDT": [100, 100, 200],
            "card1": [1111, 1111, 1111],
            "addr1": [10, 10, 10],
            "DeviceInfo": ["device-a", "device-a", "device-a"],
            "R_emaildomain": ["example.com", "example.com", "example.com"],
        }
    )

    features = build_temporal_relationship_features(frame)

    # Same-time transactions have no strictly earlier relationship history.
    assert features.loc[0, "payment_device_profile_prior_total"] == 0
    assert features.loc[1, "payment_device_profile_prior_total"] == 0

    # The later transaction sees both prior same-time transactions.
    assert features.loc[2, "payment_device_profile_prior_total"] == 2
    assert features.loc[2, "payment_receiver_profile_prior_total"] == 2


def test_missing_relationship_data_falls_back_to_zero_evidence():
    frame = pd.DataFrame(
        {
            "TransactionDT": [100, 200],
            "card1": [1111, 1111],
            "addr1": [10, 10],
            "DeviceInfo": [pd.NA, pd.NA],
            "R_emaildomain": [pd.NA, pd.NA],
        }
    )

    features = build_temporal_relationship_features(frame)

    assert (features["graph_key_coverage"] == 0).all()
    assert (features["graph_active_prior_keys"] == 0).all()
    assert (features["graph_prior_1h_max"] == 0).all()
    assert (features["graph_prior_24h_max"] == 0).all()
