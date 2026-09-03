from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from linkrisk.baseline import (
    BASE_RAW_FEATURES,
    ID_COL,
    TARGET,
    TIME_COL,
    choose_threshold_for_fpr,
    evaluate_scores,
    merge_transaction_identity,
    select_baseline_features,
)
from linkrisk.data import chronological_split

DATA_DIR = ROOT / "data" / "raw"
RESULTS_DIR = ROOT / "artifacts" / "results"
MODEL_DIR = ROOT / ".linkrisk" / "experiments" / "autogluon_challenger"
OUT = RESULTS_DIR / "autogluon_challenger_validation.json"


def load_data() -> pd.DataFrame:
    tx_path = DATA_DIR / "train_transaction.csv"
    id_path = DATA_DIR / "train_identity.csv"
    required_tx = {ID_COL, TIME_COL, TARGET, *BASE_RAW_FEATURES}
    required_id = {ID_COL, *BASE_RAW_FEATURES}
    tx = pd.read_csv(tx_path, usecols=lambda c: c in required_tx, low_memory=False)
    identity = pd.read_csv(id_path, usecols=lambda c: c in required_id, low_memory=False)
    return merge_transaction_identity(tx, identity)


def positive_scores(predictor: Any, frame: pd.DataFrame) -> np.ndarray:
    """Return positive-class probabilities across AutoGluon minor API variants."""
    probabilities = predictor.predict_proba(frame)
    if isinstance(probabilities, pd.DataFrame):
        positive = getattr(predictor, "positive_class", 1)
        if positive in probabilities.columns:
            return probabilities[positive].to_numpy(dtype=float)
        if 1 in probabilities.columns:
            return probabilities[1].to_numpy(dtype=float)
        return probabilities.iloc[:, -1].to_numpy(dtype=float)
    if isinstance(probabilities, pd.Series):
        return probabilities.to_numpy(dtype=float)
    values = np.asarray(probabilities)
    if values.ndim == 2:
        return values[:, -1].astype(float)
    return values.astype(float)


def load_frozen_baseline_metrics() -> dict[str, Any] | None:
    path = RESULTS_DIR / "baseline_validation.json"
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload.get("metrics", payload)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Development-only AutoGluon challenger for LinkRisk. The old final test is not scored."
    )
    parser.add_argument("--time-limit", type=int, default=1800, help="AutoGluon fit time limit in seconds (default: 1800).")
    parser.add_argument("--presets", default="medium_quality", help="AutoGluon preset (default: medium_quality).")
    parser.add_argument("--target-fpr", type=float, default=0.01, help="Internal tuning FPR used to freeze the challenger threshold.")
    parser.add_argument("--internal-train-frac", type=float, default=0.85, help="Fraction of the historical train partition used to fit models.")
    parser.add_argument("--keep-models", action="store_true", help="Keep AutoGluon model files under .linkrisk/experiments.")
    parser.add_argument("--overwrite", action="store_true", help="Delete a previous local challenger directory before fitting.")
    args = parser.parse_args()

    try:
        from autogluon.tabular import TabularPredictor
    except ImportError as exc:
        raise SystemExit(
            "AutoGluon is not installed in this environment. Install only for research with:\n"
            "  pip install -r requirements-experiments.txt\n"
            "Do not add AutoGluon to the production Render requirements."
        ) from exc

    if not (0.5 <= args.internal_train_frac < 1.0):
        raise SystemExit("--internal-train-frac must be in [0.5, 1.0).")

    print("=== LinkRisk AutoGluon Challenger ===\n")
    print("DEVELOPMENT VALIDATION ONLY.")
    print("The previously opened final test partition is not scored, thresholded, or used for model selection.\n")

    data = load_data()
    train, validation, old_final_partition = chronological_split(data)
    old_final_rows = len(old_final_partition)
    del old_final_partition
    del data

    train = train.sort_values(TIME_COL, kind="mergesort").reset_index(drop=True)
    cut = int(len(train) * args.internal_train_frac)
    fit_rows = train.iloc[:cut].copy()
    tune_rows = train.iloc[cut:].copy()

    features = select_baseline_features(fit_rows)
    if not features:
        raise SystemExit("No frozen baseline feature columns were found.")

    frozen_feature_path = RESULTS_DIR / "baseline_features.json"
    feature_contract_matches = None
    if frozen_feature_path.exists():
        with frozen_feature_path.open("r", encoding="utf-8") as handle:
            frozen_features = json.load(handle)
        if isinstance(frozen_features, dict):
            frozen_features = frozen_features.get("features", frozen_features.get("feature_columns", []))
        feature_contract_matches = list(frozen_features) == list(features)

    print(f"Historical fit rows : {len(fit_rows):,}")
    print(f"Internal tune rows  : {len(tune_rows):,}")
    print(f"Dev validation rows : {len(validation):,}")
    print(f"Feature columns      : {len(features)}")
    print(f"Old final rows       : {old_final_rows:,} (not scored)\n")

    fit_data = fit_rows[features + [TARGET]].copy()
    tune_data = tune_rows[features + [TARGET]].copy()
    validation_x = validation[features].copy()
    validation_y = validation[TARGET].astype(np.int8).to_numpy()

    if MODEL_DIR.exists() and args.overwrite:
        shutil.rmtree(MODEL_DIR)
    MODEL_DIR.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Training AutoGluon ({args.presets}, time_limit={args.time_limit}s)...")
    predictor = TabularPredictor(
        label=TARGET,
        problem_type="binary",
        eval_metric="average_precision",
        positive_class=1,
        path=str(MODEL_DIR),
        verbosity=2,
    )
    predictor.fit(
        train_data=fit_data,
        tuning_data=tune_data,
        presets=args.presets,
        time_limit=args.time_limit,
    )

    print("Freezing challenger threshold on the internal historical tune slice...")
    tune_scores = positive_scores(predictor, tune_data[features])
    tune_y = tune_data[TARGET].astype(np.int8).to_numpy()
    threshold = choose_threshold_for_fpr(tune_y, tune_scores, target_fpr=args.target_fpr)
    tune_metrics = evaluate_scores(tune_y, tune_scores, threshold)

    print("Evaluating once on development validation...")
    validation_scores = positive_scores(predictor, validation_x)
    challenger_metrics = evaluate_scores(validation_y, validation_scores, threshold)
    frozen_baseline = load_frozen_baseline_metrics()

    try:
        leaderboard_df = predictor.leaderboard(tune_data, silent=True)
        leaderboard = leaderboard_df.head(12).replace({np.nan: None}).to_dict(orient="records")
    except Exception:
        leaderboard = []

    payload: dict[str, Any] = {
        "experiment": "autogluon_tabular_challenger",
        "status": "development_validation_only",
        "scientific_boundary": {
            "old_final_test_rows": old_final_rows,
            "old_final_test_scored": False,
            "old_final_test_used_for_threshold": False,
            "old_final_test_used_for_model_selection": False,
            "threshold_source": "chronological tail of historical train partition",
        },
        "configuration": {
            "autogluon_presets": args.presets,
            "time_limit_seconds": args.time_limit,
            "target_fpr": args.target_fpr,
            "internal_train_fraction": args.internal_train_frac,
            "feature_count": len(features),
            "feature_contract_matches_frozen_baseline": feature_contract_matches,
            "eval_metric": "average_precision",
        },
        "internal_tune": tune_metrics,
        "development_validation": challenger_metrics,
        "frozen_baseline_validation": frozen_baseline,
        "leaderboard_internal_tune_top": leaderboard,
    }

    if frozen_baseline:
        payload["delta_vs_frozen_baseline_validation"] = {
            "precision_pp": 100.0 * (challenger_metrics["precision"] - float(frozen_baseline.get("precision", 0.0))),
            "recall_pp": 100.0 * (challenger_metrics["recall"] - float(frozen_baseline.get("recall", 0.0))),
            "pr_auc": challenger_metrics["pr_auc"] - float(frozen_baseline.get("pr_auc", 0.0)),
            "fpr_pp": 100.0 * (challenger_metrics["false_positive_rate"] - float(frozen_baseline.get("false_positive_rate", 0.0))),
            "true_positives": challenger_metrics["true_positives"] - int(frozen_baseline.get("true_positives", 0)),
            "false_positives": challenger_metrics["false_positives"] - int(frozen_baseline.get("false_positives", 0)),
        }

    with OUT.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    print("\n=== AUTOGLOUON DEVELOPMENT RESULT ===")
    print(f"threshold : {challenger_metrics['threshold']:.9f} (frozen on internal tune)")
    print(f"precision : {challenger_metrics['precision']:.4f}")
    print(f"recall    : {challenger_metrics['recall']:.4f}")
    print(f"PR-AUC    : {challenger_metrics['pr_auc']:.4f}")
    print(f"FPR       : {challenger_metrics['false_positive_rate'] * 100:.4f}%")
    print(
        "TP/FP/TN/FN: "
        f"{challenger_metrics['true_positives']}/"
        f"{challenger_metrics['false_positives']}/"
        f"{challenger_metrics['true_negatives']}/"
        f"{challenger_metrics['false_negatives']}"
    )

    if frozen_baseline:
        delta = payload["delta_vs_frozen_baseline_validation"]
        print("\nDelta vs frozen XGBoost baseline validation")
        print(f"  recall    : {delta['recall_pp']:+.2f} pp")
        print(f"  precision : {delta['precision_pp']:+.2f} pp")
        print(f"  PR-AUC    : {delta['pr_auc']:+.4f}")
        print(f"  FPR       : {delta['fpr_pp']:+.3f} pp")
        print(f"  TP / FP   : {delta['true_positives']:+d} / {delta['false_positives']:+d}")

    print(f"\nSaved {OUT.relative_to(ROOT)}")
    print("This is a challenger result only; do not relabel it as a new held-out test.")

    if not args.keep_models:
        shutil.rmtree(MODEL_DIR, ignore_errors=True)


if __name__ == "__main__":
    main()
