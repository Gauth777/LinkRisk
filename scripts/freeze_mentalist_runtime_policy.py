from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "artifacts" / "results"
OUT = RESULTS_DIR / "mentalist_runtime_policy.json"
PRIMARY_JANE_BUDGET = 0.0100
VALIDATION_INTERVENTION_TARGET = 0.0600


def _load(name: str) -> dict:
    path = RESULTS_DIR / name
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Run the Mentalist development evaluators first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    baseline = _load("baseline_validation.json")
    v8 = _load("mentalist_v8_investigator_validation.json")
    v10 = _load("mentalist_v10_reallocation_validation.json")

    if not bool(v8.get("usefulness_gate", {}).get("pass", False)):
        raise RuntimeError("Mentalist v0.8 did not pass; runtime policy cannot be frozen")
    if not bool(v10.get("promotion", {}).get("pass", False)):
        raise RuntimeError("Mentalist v1.0 did not pass; runtime policy cannot be frozen")

    primary = next(
        row
        for row in v8["verify_budgets"]
        if abs(float(row["budget"]) - PRIMARY_JANE_BUDGET) < 1e-12
    )
    jane_threshold = float(primary["jane_score_threshold"])

    v10_stored = float(v10["jane"]["v8_stored_cutoff"])
    if abs(jane_threshold - v10_stored) > 1e-12:
        raise RuntimeError(
            "v0.8 and v1.0 disagree on the frozen Jane cutoff; refusing to freeze"
        )

    displacement = v10["evicted_v5_verify_cases"].get("max_v5_risk")
    if displacement is None:
        raise RuntimeError("v1.0 did not record a displacement boundary")

    baseline_review_threshold = float(baseline["metrics"]["threshold"])
    min_clues = int(v10["jane"]["min_clue_families"])
    payload = {
        "version": "mentalist_v1.0_runtime",
        "source_experiments": {
            "baseline_review_cutoff": "baseline_validation",
            "jane_cutoff": "mentalist_v0.8_evidence_gated_investigator",
            "displacement_cutoff": "mentalist_v1.0_one_for_one_reallocation",
        },
        "min_clue_families": min_clues,
        "jane_score_threshold": jane_threshold,
        "baseline_review_threshold": baseline_review_threshold,
        "v5_verify_displacement_threshold": float(displacement),
        "validation_intervention_target": VALIDATION_INTERVENTION_TARGET,
        "held_out_test_status": "sealed",
        "notes": [
            "Thresholds are operating boundaries, not calibrated fraud probabilities.",
            "Jane eligibility preserves the frozen transaction-baseline REVIEW boundary used by v0.8/v1.0.",
            "v0.5 REVIEW remains immutable.",
            "Previous fraud remains evidence, not automatic guilt.",
            "Future traffic is not used by the runtime decision rule.",
        ],
    }

    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("=== Mentalist v1.0 Runtime Policy Freeze ===")
    print(f"Minimum independent clue families: {min_clues}")
    print(f"Jane score threshold:              {jane_threshold:.15f}")
    print(f"Baseline REVIEW threshold:         {baseline_review_threshold:.15f}")
    print(f"v0.5 VERIFY displacement boundary: {float(displacement):.15f}")
    print(f"Validation intervention target:    {100*VALIDATION_INTERVENTION_TARGET:.2f}%")
    print("Held-out test:                     SEALED")
    print(f"Saved {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
