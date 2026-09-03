from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

import joblib
import numpy as np
import pandas as pd
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from backend.model_assets import ensure_model_assets
from linkrisk.baseline import (
    BASE_RAW_FEATURES,
    ID_COL,
    TARGET,
    TIME_COL,
    build_preprocessor,
    choose_threshold_for_fpr,
    evaluate_scores,
    merge_transaction_identity,
    select_baseline_features,
)
from linkrisk.data import chronological_split
from linkrisk.relationship_features_v4 import (
    RELATIONSHIP_FEATURES_V4,
    build_relationship_features_v4,
)

DATA_DIR = ROOT / "data" / "raw"
MODEL_DIR = ROOT / "artifacts" / "models"
RESULTS_DIR = ROOT / "artifacts" / "results"
OUT = RESULTS_DIR / "graph_xgb_fusion_validation.json"


def load_data() -> pd.DataFrame:
    tx_path = DATA_DIR / "train_transaction.csv"
    id_path = DATA_DIR / "train_identity.csv"
    required_tx = {ID_COL, TIME_COL, TARGET, *BASE_RAW_FEATURES}
    required_id = {ID_COL, *BASE_RAW_FEATURES}
    tx = pd.read_csv(tx_path, usecols=lambda c: c in required_tx, low_memory=False)
    identity = pd.read_csv(id_path, usecols=lambda c: c in required_id, low_memory=False)
    return merge_transaction_identity(tx, identity)


def make_model(y: np.ndarray, random_state: int = 42) -> XGBClassifier:
    negatives = int((y == 0).sum())
    positives = int((y == 1).sum())
    scale_pos_weight = negatives / max(positives, 1)
    return XGBClassifier(
        objective="binary:logistic",
        eval_metric="aucpr",
        n_estimators=350,
        learning_rate=0.05,
        max_depth=6,
        min_child_weight=2,
        subsample=0.85,
        colsample_bytree=0.85,
        reg_lambda=1.0,
        scale_pos_weight=scale_pos_weight,
        tree_method="hist",
        n_jobs=-1,
        random_state=random_state,
    )


def train_and_score(
    frame: pd.DataFrame,
    feature_columns: list[str],
    *,
    fit_rows: int,
    val_start: int,
    target_fpr: float,
    random_state: int,
) -> tuple[dict[str, Any], dict[str, Any], XGBClassifier, Any, np.ndarray]:
    fit_x = frame.iloc[:fit_rows][feature_columns]
    tune_x = frame.iloc[fit_rows:val_start][feature_columns]
    val_x = frame.iloc[val_start:][feature_columns]

    fit_y = frame.iloc[:fit_rows][TARGET].astype(np.int8).to_numpy()
    tune_y = frame.iloc[fit_rows:val_start][TARGET].astype(np.int8).to_numpy()
    val_y = frame.iloc[val_start:][TARGET].astype(np.int8).to_numpy()

    preprocessor = build_preprocessor(fit_x)
    fit_matrix = preprocessor.fit_transform(fit_x)
    tune_matrix = preprocessor.transform(tune_x)
    val_matrix = preprocessor.transform(val_x)

    model = make_model(fit_y, random_state=random_state)
    model.fit(fit_matrix, fit_y, eval_set=[(tune_matrix, tune_y)], verbose=False)

    tune_scores = model.predict_proba(tune_matrix)[:, 1]
    threshold = choose_threshold_for_fpr(tune_y, tune_scores, target_fpr=target_fpr)
    tune_metrics = evaluate_scores(tune_y, tune_scores, threshold)

    val_scores = model.predict_proba(val_matrix)[:, 1]
    val_metrics = evaluate_scores(val_y, val_scores, threshold)
    return tune_metrics, val_metrics, model, preprocessor, val_scores


def score_frozen_baseline(
    frame: pd.DataFrame,
    *,
    fit_rows: int,
    val_start: int,
    target_fpr: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    ensure_model_assets(ROOT)
    preprocessor = joblib.load(MODEL_DIR / "baseline_preprocessor.joblib")
    model = joblib.load(MODEL_DIR / "baseline_xgboost.joblib")
    features = select_baseline_features(frame)
    matrix = preprocessor.transform(frame[features])
    scores = model.predict_proba(matrix)[:, 1]

    tune_y = frame.iloc[fit_rows:val_start][TARGET].astype(np.int8).to_numpy()
    tune_scores = scores[fit_rows:val_start]
    threshold = choose_threshold_for_fpr(tune_y, tune_scores, target_fpr=target_fpr)
    tune_metrics = evaluate_scores(tune_y, tune_scores, threshold)

    val_y = frame.iloc[val_start:][TARGET].astype(np.int8).to_numpy()
    val_metrics = evaluate_scores(val_y, scores[val_start:], threshold)
    return tune_metrics, val_metrics


def delta(after: dict[str, Any], before: dict[str, Any]) -> dict[str, Any]:
    return {
        "pr_auc": after["pr_auc"] - before["pr_auc"],
        "recall_pp": 100.0 * (after["recall"] - before["recall"]),
        "precision_pp": 100.0 * (after["precision"] - before["precision"]),
        "fpr_pp": 100.0 * (after["false_positive_rate"] - before["false_positive_rate"]),
        "true_positives": after["true_positives"] - before["true_positives"],
        "false_positives": after["false_positives"] - before["false_positives"],
    }


def feature_importance_payload(
    model: XGBClassifier,
    preprocessor: Any,
    graph_feature_names: set[str],
    limit: int = 20,
) -> dict[str, list[dict[str, Any]]]:
    try:
        names = [str(name) for name in preprocessor.get_feature_names_out()]
    except Exception:
        names = [f"f{i}" for i in range(len(model.feature_importances_))]

    values = np.asarray(model.feature_importances_, dtype=float)
    pairs = sorted(zip(names, values), key=lambda item: item[1], reverse=True)

    overall = [
        {"feature": name, "importance": float(value)}
        for name, value in pairs[:limit]
    ]
    graph_only = [
        {"feature": name, "importance": float(value)}
        for name, value in pairs
        if name in graph_feature_names
    ][:limit]
    return {"overall": overall, "graph_only": graph_only}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Causal graph-derived relationship features fused with XGBoost. "
            "Development validation only; the previously opened final partition is never scored."
        )
    )
    parser.add_argument("--train-rows", type=int, default=120_000)
    parser.add_argument("--validation-rows", type=int, default=30_000)
    parser.add_argument("--tune-frac", type=float, default=0.15)
    parser.add_argument("--target-fpr", type=float, default=0.01)
    parser.add_argument("--random-state", type=int, default=42)
    args = parser.parse_args()

    if not (0.05 <= args.tune_frac <= 0.4):
        raise SystemExit("--tune-frac must be between 0.05 and 0.40")

    print("=== LinkRisk Causal Graph-Enhanced XGBoost ===\n")
    print("DEVELOPMENT VALIDATION ONLY.")
    print("Graph features use strictly prior transaction structure; same-timestamp rows are isolated.")
    print("The previously opened final partition is not scored, thresholded, or used for model selection.\n")

    merged = load_data()
    historical_train, validation, old_final_partition = chronological_split(merged)
    old_final_rows = len(old_final_partition)
    del old_final_partition
    del merged

    historical_train = historical_train.sort_values(TIME_COL, kind="mergesort")
    validation = validation.sort_values(TIME_COL, kind="mergesort")
    sampled_train = historical_train.tail(min(args.train_rows, len(historical_train))).copy()
    sampled_validation = validation.head(min(args.validation_rows, len(validation))).copy()

    sampled_train = sampled_train.reset_index(drop=True)
    sampled_validation = sampled_validation.reset_index(drop=True)
    tune_rows = max(1, int(round(len(sampled_train) * args.tune_frac)))
    fit_rows = len(sampled_train) - tune_rows
    frame = pd.concat([sampled_train, sampled_validation], ignore_index=True)
    val_start = len(sampled_train)

    print(f"Historical sample       : {len(sampled_train):,} ({fit_rows:,} fit / {tune_rows:,} tune)")
    print(f"Development validation : {len(sampled_validation):,}")
    print(f"Old final rows          : {old_final_rows:,} (not scored)\n")

    print("Building causal graph/relationship features...")
    relationship = build_relationship_features_v4(frame)
    graph_columns = [*RELATIONSHIP_FEATURES_V4, "graph_confidence_v4"]
    for column in graph_columns:
        frame[column] = relationship[column].astype(np.float32)

    raw_columns = select_baseline_features(frame)
    fusion_columns = [*raw_columns, *graph_columns]
    print(f"Raw transaction features : {len(raw_columns)}")
    print(f"Graph-derived features   : {len(graph_columns)}")
    print(f"Fusion feature count     : {len(fusion_columns)}\n")

    print("Training matched tabular-only XGBoost control...")
    tab_tune, tab_val, _, _, _ = train_and_score(
        frame,
        raw_columns,
        fit_rows=fit_rows,
        val_start=val_start,
        target_fpr=args.target_fpr,
        random_state=args.random_state,
    )

    print("Training graph-enhanced XGBoost challenger...")
    graph_tune, graph_val, graph_model, graph_preprocessor, _ = train_and_score(
        frame,
        fusion_columns,
        fit_rows=fit_rows,
        val_start=val_start,
        target_fpr=args.target_fpr,
        random_state=args.random_state,
    )

    print("Scoring frozen product baseline on the same slice for reference...")
    frozen_tune, frozen_val = score_frozen_baseline(
        frame,
        fit_rows=fit_rows,
        val_start=val_start,
        target_fpr=args.target_fpr,
    )

    graph_vs_tab = delta(graph_val, tab_val)
    graph_vs_frozen = delta(graph_val, frozen_val)

    # A challenger is only interesting if graph information buys a material gain.
    promising = bool(
        (
            graph_val["pr_auc"] >= frozen_val["pr_auc"] + 0.015
            and graph_val["recall"] >= frozen_val["recall"]
        )
        or (
            graph_val["recall"] >= frozen_val["recall"] + 0.02
            and graph_val["false_positive_rate"] <= frozen_val["false_positive_rate"] + 0.001
            and graph_val["pr_auc"] >= frozen_val["pr_auc"]
        )
    )

    importances = feature_importance_payload(
        graph_model,
        graph_preprocessor,
        set(graph_columns),
    )

    payload = {
        "experiment": "causal_graph_features_plus_xgboost_fusion",
        "status": "development_validation_only",
        "scientific_boundary": {
            "old_final_test_rows": old_final_rows,
            "old_final_test_scored": False,
            "old_final_test_labels_used": False,
            "validation_labels_used_for_training": False,
            "validation_labels_used_for_thresholding": False,
            "graph_features_use_future_rows": False,
            "graph_features_use_labels": False,
            "same_timestamp_isolation": True,
            "note": (
                "Relationship features are generated causally from strictly earlier transactions. "
                "Earlier validation transactions may become history for later validation transactions, matching live availability."
            ),
        },
        "sample": {
            "historical_train_rows": len(sampled_train),
            "fit_rows": fit_rows,
            "internal_tune_rows": tune_rows,
            "validation_rows": len(sampled_validation),
        },
        "configuration": {
            "raw_transaction_features": len(raw_columns),
            "graph_derived_features": len(graph_columns),
            "fusion_features": len(fusion_columns),
            "target_fpr": args.target_fpr,
            "xgboost_hyperparameters_matched_between_control_and_fusion": True,
        },
        "matched_tabular_control_internal_tune": tab_tune,
        "matched_tabular_control_validation": tab_val,
        "graph_xgb_internal_tune": graph_tune,
        "graph_xgb_validation": graph_val,
        "frozen_product_baseline_internal_tune": frozen_tune,
        "frozen_product_baseline_validation": frozen_val,
        "delta_graph_vs_matched_tabular_control": graph_vs_tab,
        "delta_graph_vs_frozen_product_baseline": graph_vs_frozen,
        "acceptance_gate": {
            "promising_for_followup": promising,
            "rule": (
                "PR-AUC >= frozen + 0.015 with no recall loss, OR recall >= frozen + 2pp "
                "with <=0.1pp FPR increase and no PR-AUC loss."
            ),
        },
        "feature_importance": importances,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("\n=== GRAPH-ENHANCED XGBOOST DEVELOPMENT RESULT ===")
    print(f"Matched tabular control : PR-AUC {tab_val['pr_auc']:.4f} | recall {100*tab_val['recall']:.2f}% | precision {100*tab_val['precision']:.2f}% | FPR {100*tab_val['false_positive_rate']:.3f}%")
    print(f"Graph + XGBoost         : PR-AUC {graph_val['pr_auc']:.4f} | recall {100*graph_val['recall']:.2f}% | precision {100*graph_val['precision']:.2f}% | FPR {100*graph_val['false_positive_rate']:.3f}%")
    print(f"Frozen product baseline : PR-AUC {frozen_val['pr_auc']:.4f} | recall {100*frozen_val['recall']:.2f}% | precision {100*frozen_val['precision']:.2f}% | FPR {100*frozen_val['false_positive_rate']:.3f}%")
    print("\nDelta graph vs matched tabular control")
    print(f"  PR-AUC   : {graph_vs_tab['pr_auc']:+.4f}")
    print(f"  Recall   : {graph_vs_tab['recall_pp']:+.2f} pp")
    print(f"  Precision: {graph_vs_tab['precision_pp']:+.2f} pp")
    print(f"  FPR      : {graph_vs_tab['fpr_pp']:+.3f} pp")
    print(f"  TP / FP  : {graph_vs_tab['true_positives']:+d} / {graph_vs_tab['false_positives']:+d}")
    print("\nDelta graph vs frozen product baseline")
    print(f"  PR-AUC   : {graph_vs_frozen['pr_auc']:+.4f}")
    print(f"  Recall   : {graph_vs_frozen['recall_pp']:+.2f} pp")
    print(f"  Precision: {graph_vs_frozen['precision_pp']:+.2f} pp")
    print(f"  FPR      : {graph_vs_frozen['fpr_pp']:+.3f} pp")
    print(f"  TP / FP  : {graph_vs_frozen['true_positives']:+d} / {graph_vs_frozen['false_positives']:+d}")
    print(f"\nAcceptance gate: {'PROMISING' if promising else 'REJECT'}")
    print(f"Saved {OUT.relative_to(ROOT)}")
    print("Development result only; do not relabel it as a new held-out test.")


if __name__ == "__main__":
    main()
