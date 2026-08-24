import numpy as np

from linkrisk.fusion_v3 import fuse_signed_relationship_evidence


def test_signed_fusion_moves_both_directions():
    ml = np.array([0.80, 0.20, 0.60], dtype=float)
    rel = np.array([0.10, 0.90, 0.50], dtype=float)
    confidence = np.ones(3, dtype=float)

    fused = fuse_signed_relationship_evidence(ml, rel, confidence, beta=1.0)

    assert fused[0] < ml[0]
    assert fused[1] > ml[1]
    assert np.isclose(fused[2], ml[2])


def test_signed_fusion_exact_fallback_when_confidence_zero():
    ml = np.array([0.02, 0.37, 0.91], dtype=float)
    rel = np.array([0.99, 0.01, 0.75], dtype=float)
    confidence = np.zeros(3, dtype=float)

    fused = fuse_signed_relationship_evidence(ml, rel, confidence, beta=2.0)

    assert np.array_equal(fused, ml)
