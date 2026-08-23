import numpy as np
import pandas as pd

from linkrisk.graph_scoring import add_graph_scores, fuse_scores


def test_no_history_means_zero_confidence_and_exact_fallback():
    features = pd.DataFrame(
        {
            "payment_device_profile_prior_1h": [0],
            "payment_device_profile_prior_24h": [0],
            "payment_receiver_profile_prior_1h": [0],
            "payment_receiver_profile_prior_24h": [0],
            "graph_active_prior_keys": [0],
        }
    )
    scored = add_graph_scores(features)
    assert scored.loc[0, "graph_confidence"] == 0.0
    assert scored.loc[0, "graph_risk"] == 0.0

    ml = np.array([0.37])
    fused = fuse_scores(
        ml,
        scored["graph_risk"],
        scored["graph_confidence"],
        alpha=0.4,
    )
    assert np.allclose(fused, ml)


def test_two_active_keys_have_full_confidence():
    features = pd.DataFrame(
        {
            "payment_device_profile_prior_1h": [4],
            "payment_device_profile_prior_24h": [6],
            "payment_receiver_profile_prior_1h": [4],
            "payment_receiver_profile_prior_24h": [7],
            "graph_active_prior_keys": [2],
        }
    )
    scored = add_graph_scores(features)
    assert scored.loc[0, "graph_confidence"] == 1.0
    assert scored.loc[0, "graph_risk"] == 1.0


def test_fusion_never_reduces_ml_score():
    ml = np.array([0.1, 0.5, 0.9])
    risk = np.array([0.2, 0.7, 1.0])
    confidence = np.array([0.5, 1.0, 1.0])
    fused = fuse_scores(ml, risk, confidence, alpha=0.4)
    assert np.all(fused >= ml)
