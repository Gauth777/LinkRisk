from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "evaluate_final_heldout.py"


def _module():
    spec = importlib.util.spec_from_file_location("final_heldout", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_action_metrics_treat_verify_and_review_as_interventions() -> None:
    module = _module()
    actions = np.array(["ALLOW", "VERIFY", "REVIEW", "ALLOW", "VERIFY"], dtype=object)
    y = np.array([0, 1, 0, 1, 0], dtype=np.int8)

    metrics = module._action_metrics(actions, y)

    assert metrics["true_positives"] == 1
    assert metrics["false_positives"] == 2
    assert metrics["true_negatives"] == 1
    assert metrics["false_negatives"] == 1
    assert metrics["precision"] == 1 / 3
    assert metrics["recall"] == 1 / 2
    assert metrics["intervention_rate"] == 3 / 5


def test_transition_stats_preserve_review_and_measure_capacity_delta() -> None:
    module = _module()
    v5 = np.array(["REVIEW", "VERIFY", "ALLOW", "ALLOW"], dtype=object)
    final = np.array(["REVIEW", "ALLOW", "VERIFY", "ALLOW"], dtype=object)
    y = np.array([1, 0, 1, 0], dtype=np.int8)
    promoted = np.array([False, False, True, False])
    displaced = np.array([False, True, False, False])

    stats = module._transition_stats(v5, final, y, promoted, displaced)

    assert stats["v5_review_unchanged"] is True
    assert stats["intervention_delta_rows"] == 0
    assert stats["promoted_by_mentalist"]["frauds"] == 1
    assert stats["displaced_v5_verify"]["legitimate"] == 1


def test_final_script_has_no_test_threshold_search() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "choose_threshold_for_fpr" not in source
    assert "REVIEW_THRESHOLD" in source
    assert "--execute-final" in source
    assert "FINAL_DO_NOT_RETUNE" in source
