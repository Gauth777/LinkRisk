from __future__ import annotations

import json
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

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
from linkrisk.mentalist_features_v7 import (
    MENTALIST_FEATURES,
    build_mentalist_features_v7,
    calibrate_clue_thresholds,
    clue_activations,
)

DATA_DIR = ROOT / "data" / "raw"
MODEL_DIR = ROOT / "artifacts" / "models"
RESULTS_DIR = ROOT / "artifacts" / "results"
TARGET_FPR = 0.01
OOF_WARMUP_FRACTION = 0.40
OOF_BLOCK_FRACTION = 0.20
CLUE_QUANTILE = 0.975

# Predeclared promotion gate. We do not relax it after seeing validation output.
MIN_RECALL_LIFT = 0.010
MIN_PR_AUC_LIFT = 0.000
ALT_MIN_PR_AUC_LIFT = 0.010
ALT_MIN_RECALL_LIFT = 0.000


def load_data() -> pd.DataFrame:
    tx_path = DATA_DIR / "train_transaction.csv"
    id_path = DATA_DIR / "train_identity.csv"
    required_tx = {ID_COL, TIME_COL, TARGET, *BASE_RAW_FEATURES}
    required_id = {ID_COL, *BASE_RAW_FEATURES}
    tx = pd.read_csv(
        tx_path,
        usecols=lambda column: column in required_tx,
        low_memory=False,
    )
    identity = pd.read_csv(
        id_path,
        usecols=lambda column: column in required_id,
        low_memory=False,
    )
    return merge_transaction_identity(tx, identity)


def fit_baseline_score_model(history: pd.DataFrame) -> tuple[object, XGBClassifier, list[str]]:
    """Fit the frozen baseline architecture without consulting future labels."""
    features = select_baseline_features(history)
    x = history[features]
    y = history[TARGET].astype(np.int8).to_numpy()

    preprocessor = build_preprocessor(x)
    matrix = preprocessor.fit_transform(x)
    negatives = int((y == 0).sum())
    positives = int((y == 1).sum())

    model = XGBClassifier(
        objective="binary:logistic",
        eval_metric="aucpr",
        n_estimators=350,
        learning_rate=0.05,
        max_depth=6,
        min_child_weight=2,
        subsample=0.85,
        colsample_bytree=0.85,
        reg_lambda=1.0,
        scale_pos_weight=negatives / max(positives, 1),
        tree_method="hist",
        n_jobs=-1,
        random_state=42,
    )
    model.fit(matrix, y, verbose=False)
    return preprocessor, model, features


def chronological_oof_baseline_scores(train: pd.DataFrame) -> pd.Series:
    """Generate deployment-like baseline scores for Mentalist training.

    The first 40% is warm-up. Three expanding-window models then predict the
    next 20% blocks. A row is never scored by a baseline trained on that row or
    on future rows.
    """
    n = len(train)
    scores = pd.Series(np.nan, index=train.index, dtype=float)
    start_fraction = OOF_WARMUP_FRACTION
    fold = 1

    while start_fraction < 1.0 - 1e-9:
        history_end = int(n * start_fraction)
        block_end = min(
            int(n * (start_fraction + OOF_BLOCK_FRACTION)),
            n,
        )
        history = train.iloc[:history_end]
        block = train.iloc[history_end:block_end]
        if block.empty:
            break

        print(
            f"OOF baseline fold {fold}: train={len(history):,} "
            f"predict={len(block):,}"
        )
        preprocessor, model, features = fit_baseline_score_model(history)
        block_matrix = preprocessor.transform(block[features])
        scores.loc[block.index] = model.predict_proba(block_matrix)[:, 1]

        start_fraction += OOF_BLOCK_FRACTION
        fold += 1

    return scores


def fit_mentalist(
    features: pd.DataFrame,
    y: np.ndarray,
) -> XGBClassifier:
    negatives = int((y == 0).sum())
    positives = int((y == 1).sum())
    model = XGBClassifier(
        objective="binary:logistic",
        eval_metric="aucpr",
        n_estimators=450,
        learning_rate=0.035,
        max_depth=4,
        min_child_weight=5,
        subsample=0.85,
        colsample_bytree=0.90,
        reg_lambda=2.0,
        reg_alpha=0.20,
        scale_pos_weight=negatives / max(positives, 1),
        tree_method="hist",
        max_bin=128,
        n_jobs=-1,
        random_state=42,
    )
    model.fit(features, y, verbose=False)
    return model


def transition_stats(
    y: np.ndarray,
    baseline_pred: np.ndarray,
    mentalist_pred: np.ndarray,
) -> dict[str, int]:
    recovered_fn = int(((y == 1) & (baseline_pred == 0) & (mentalist_pred == 1)).sum())
    lost_tp = int(((y == 1) & (baseline_pred == 1) & (mentalist_pred == 0)).sum())
    removed_fp = int(((y == 0) & (baseline_pred == 1) & (mentalist_pred == 0)).sum())
    new_fp = int(((y == 0) & (baseline_pred == 0) & (mentalist_pred == 1)).sum())
    return {
        "recovered_baseline_false_negatives": recovered_fn,
        "lost_baseline_true_positives": lost_tp,
        "net_true_positive_change": recovered_fn - lost_tp,
        "removed_baseline_false_positives": removed_fp,
        "new_false_positives": new_fp,
        "net_false_positive_change": new_fp - removed_fp,
    }


def clue_segments(
    y: np.ndarray,
    baseline_pred: np.ndarray,
    mentalist_pred: np.ndarray,
    clues: pd.DataFrame,
) -> list[dict]:
    counts = clues["independent_clue_count"].to_numpy(dtype=int)
    segments: list[dict] = []
    for label, mask in (
        ("0", counts == 0),
        ("1", counts == 1),
        ("2", counts == 2),
        ("3+", counts >= 3),
    ):
        rows = int(mask.sum())
        frauds = int(((y == 1) & mask).sum())
        baseline_tp = int(((y == 1) & (baseline_pred == 1) & mask).sum())
        mentalist_tp = int(((y == 1) & (mentalist_pred == 1) & mask).sum())
        recovered = int(
            ((y == 1) & (baseline_pred == 0) & (mentalist_pred == 1) & mask).sum()
        )
        segments.append(
            {
                "independent_clue_families": label,
                "rows": rows,
                "frauds": frauds,
                "fraud_rate": frauds / rows if rows else 0.0,
                "baseline_recall": baseline_tp / frauds if frauds else 0.0,
                "mentalist_recall": mentalist_tp / frauds if frauds else 0.0,
                "recovered_baseline_false_negatives": recovered,
            }
        )
    return segments


def promotion_decision(baseline: dict, mentalist: dict) -> dict:
    recall_lift = mentalist["recall"] - baseline["recall"]
    pr_auc_lift = mentalist["pr_auc"] - baseline["pr_auc"]
    fpr_ok = mentalist["false_positive_rate"] <= TARGET_FPR + 1e-12
    primary = recall_lift >= MIN_RECALL_LIFT and pr_auc_lift >= MIN_PR_AUC_LIFT
    alternate = (
        pr_auc_lift >= ALT_MIN_PR_AUC_LIFT
        and recall_lift >= ALT_MIN_RECALL_LIFT
    )
    return {
        "promote_candidate": bool(fpr_ok and (primary or alternate)),
        "recall_lift": float(recall_lift),
        "pr_auc_lift": float(pr_auc_lift),
        "fpr_within_budget": bool(fpr_ok),
        "rule": {
            "primary": {
                "min_recall_lift": MIN_RECALL_LIFT,
                "min_pr_auc_lift": MIN_PR_AUC_LIFT,
            },
            "alternate": {
                "min_pr_auc_lift": ALT_MIN_PR_AUC_LIFT,
                "min_recall_lift": ALT_MIN_RECALL_LIFT,
            },
            "max_validation_fpr": TARGET_FPR,
        },
    }


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading IEEE-CIS development data...")
    data = load_data()
    train, validation, sealed_test = chronological_split(data)
    sealed_test_rows = len(sealed_test)
    del sealed_test
    del data

    print(f"Train rows:      {len(train):,}")
    print(f"Validation rows: {len(validation):,}")
    print(f"Sealed test rows:{sealed_test_rows:,} (not evaluated)")

    # Build structural features causally across train -> validation. The builder
    # never reads TARGET; validation rows can use prior transaction structure but
    # not current/future labels.
    print("Building proactive temporal/network features...")
    development = pd.concat([train, validation], axis=0)
    proactive = build_mentalist_features_v7(development)
    train_proactive = proactive.loc[train.index]
    val_proactive = proactive.loc[validation.index]
    del proactive
    del development

    print("Generating chronological out-of-fold baseline scores...")
    oof_scores = chronological_oof_baseline_scores(train)
    oof_mask = oof_scores.notna()
    if int(oof_mask.sum()) < 1000:
        raise RuntimeError("Too few chronological OOF rows for Mentalist training")

    y_train_oof = train.loc[oof_mask, TARGET].astype(np.int8).to_numpy()
    x_train = train_proactive.loc[oof_mask, MENTALIST_FEATURES].copy()
    x_train.insert(0, "baseline_oof_risk", oof_scores.loc[oof_mask].to_numpy(dtype=float))
    x_train = x_train.replace([np.inf, -np.inf], np.nan).fillna(0.0).astype(np.float32)

    clue_thresholds = calibrate_clue_thresholds(
        train_proactive.loc[oof_mask],
        y_train_oof,
        quantile=CLUE_QUANTILE,
    )

    print(
        f"Training Mentalist on {len(x_train):,} deployment-like OOF rows "
        f"with {len(x_train.columns)} inputs..."
    )
    mentalist = fit_mentalist(x_train, y_train_oof)

    # Frozen full-train baseline provides the validation risk input.
    with (RESULTS_DIR / "baseline_features.json").open("r", encoding="utf-8") as f:
        baseline_features = json.load(f)
    with (RESULTS_DIR / "baseline_validation.json").open("r", encoding="utf-8") as f:
        baseline_snapshot = json.load(f)
    baseline_threshold = float(baseline_snapshot["metrics"]["threshold"])

    baseline_preprocessor = joblib.load(MODEL_DIR / "baseline_preprocessor.joblib")
    baseline_model = joblib.load(MODEL_DIR / "baseline_xgboost.joblib")
    val_raw = baseline_preprocessor.transform(validation[baseline_features])
    baseline_scores = baseline_model.predict_proba(val_raw)[:, 1]

    x_val = val_proactive[MENTALIST_FEATURES].copy()
    x_val.insert(0, "baseline_oof_risk", baseline_scores)
    x_val = x_val.replace([np.inf, -np.inf], np.nan).fillna(0.0).astype(np.float32)
    mentalist_scores = mentalist.predict_proba(x_val)[:, 1]

    y_val = validation[TARGET].astype(np.int8).to_numpy()
    mentalist_threshold = choose_threshold_for_fpr(
        y_val,
        mentalist_scores,
        target_fpr=TARGET_FPR,
    )

    baseline_metrics = evaluate_scores(y_val, baseline_scores, baseline_threshold)
    mentalist_metrics = evaluate_scores(y_val, mentalist_scores, mentalist_threshold)
    baseline_pred = (baseline_scores >= baseline_threshold).astype(np.int8)
    mentalist_pred = (mentalist_scores >= mentalist_threshold).astype(np.int8)

    transitions = transition_stats(y_val, baseline_pred, mentalist_pred)
    val_clues = clue_activations(val_proactive, clue_thresholds)
    segments = clue_segments(y_val, baseline_pred, mentalist_pred, val_clues)
    promotion = promotion_decision(baseline_metrics, mentalist_metrics)

    feature_importance = sorted(
        [
            {"feature": name, "importance": float(value)}
            for name, value in zip(x_train.columns, mentalist.feature_importances_)
        ],
        key=lambda row: row["importance"],
        reverse=True,
    )

    payload = {
        "experiment": "mentalist_v0.7_proactive_deduction",
        "hypothesis": (
            "Causal temporal/network clues can recover transaction-model misses "
            "without requiring prior confirmed-fraud memory."
        ),
        "held_out_test": {
            "status": "sealed",
            "rows": sealed_test_rows,
            "labels_used": False,
        },
        "training": {
            "total_train_rows": len(train),
            "oof_training_rows": int(oof_mask.sum()),
            "oof_warmup_fraction": OOF_WARMUP_FRACTION,
            "oof_block_fraction": OOF_BLOCK_FRACTION,
            "mentalist_feature_count": len(x_train.columns),
            "confirmed_fraud_memory_features": 0,
        },
        "baseline": baseline_metrics,
        "mentalist": mentalist_metrics,
        "transition_vs_baseline": transitions,
        "clue_quantile": CLUE_QUANTILE,
        "clue_thresholds": clue_thresholds,
        "clue_segments": segments,
        "feature_importance": feature_importance,
        "promotion": promotion,
    }

    joblib.dump(mentalist, MODEL_DIR / "mentalist_v7_candidate.joblib")
    (RESULTS_DIR / "mentalist_v7_validation.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )

    print("\n=== Mentalist v0.7 — Proactive Deduction ===")
    print("No confirmed-fraud memory is used as model input.")
    print("Held-out test remains sealed.\n")
    print("Frozen baseline")
    print(f"  Precision: {baseline_metrics['precision']:.4f}")
    print(f"  Recall:    {baseline_metrics['recall']:.4f}")
    print(f"  PR-AUC:    {baseline_metrics['pr_auc']:.4f}")
    print(f"  FPR:       {100 * baseline_metrics['false_positive_rate']:.4f}%")
    print("Mentalist")
    print(f"  Threshold: {mentalist_threshold:.9f}")
    print(f"  Precision: {mentalist_metrics['precision']:.4f}")
    print(f"  Recall:    {mentalist_metrics['recall']:.4f}")
    print(f"  PR-AUC:    {mentalist_metrics['pr_auc']:.4f}")
    print(f"  FPR:       {100 * mentalist_metrics['false_positive_rate']:.4f}%")
    print("\nDecision delta")
    print(
        "  Recovered baseline FNs: "
        f"{transitions['recovered_baseline_false_negatives']}"
    )
    print(f"  Lost baseline TPs:       {transitions['lost_baseline_true_positives']}")
    print(f"  Net TP change:           {transitions['net_true_positive_change']:+d}")
    print(f"  Net FP change:           {transitions['net_false_positive_change']:+d}")
    print("\nClue-family segments")
    for row in segments:
        print(
            f"  clues={row['independent_clue_families']:>2} "
            f"rows={row['rows']:>6,} fraud_rate={100 * row['fraud_rate']:>6.2f}% "
            f"base_R={100 * row['baseline_recall']:>6.2f}% "
            f"Jane_R={100 * row['mentalist_recall']:>6.2f}% "
            f"recovered={row['recovered_baseline_false_negatives']:>4}"
        )
    print("\nPromotion gate")
    print(f"  Recall lift: {promotion['recall_lift']:+.4f}")
    print(f"  PR-AUC lift: {promotion['pr_auc_lift']:+.4f}")
    print(
        "  Candidate status: "
        + ("PASS" if promotion["promote_candidate"] else "FAIL — keep stable v0.5")
    )
    print("\nSaved artifacts/results/mentalist_v7_validation.json")


if __name__ == "__main__":
    main()
