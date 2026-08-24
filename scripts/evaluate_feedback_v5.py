from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
import json
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
    choose_threshold_for_fpr,
    evaluate_scores,
    merge_transaction_identity,
)
from linkrisk.data import chronological_split
from linkrisk.relationship_features_v4 import (
    DEVICE_CONTEXT_COLUMNS,
    PAYMENT_PROFILE_COLUMNS,
    STRONG_DEVICE_COLUMNS,
    STRONG_RECEIVER_COLUMNS,
    build_relationship_features_v4,
    make_composite_key,
    relationship_matrix_v4,
)

DATA_DIR = ROOT / "data" / "raw"
MODEL_DIR = ROOT / "artifacts" / "models"
RESULTS_DIR = ROOT / "artifacts" / "results"
TARGET_FPR = 0.01
LABEL_DELAY = 72 * 60 * 60
WINDOW_30D = 30 * 24 * 60 * 60
GATE_GRID = [0.25, 0.50, 0.75, 1.00]

FEEDBACK_KEYS = {
    "profile": PAYMENT_PROFILE_COLUMNS,
    "device": STRONG_DEVICE_COLUMNS,
    "receiver": STRONG_RECEIVER_COLUMNS,
    "device_context": DEVICE_CONTEXT_COLUMNS,
}

FEEDBACK_FEATURES: list[str] = []
for key in FEEDBACK_KEYS:
    FEEDBACK_FEATURES += [
        f"log_{key}_confirmed_total",
        f"log_{key}_confirmed_fraud_total",
        f"{key}_confirmed_fraud_rate",
        f"log_{key}_confirmed_fraud_30d",
        f"{key}_has_confirmed_fraud",
    ]
FEEDBACK_FEATURES += [
    "feedback_history_channels",
    "confirmed_fraud_channels",
    "any_strong_confirmed_fraud",
    "max_confirmed_fraud_rate",
    "feedback_total_support_log",
]


class History:
    __slots__ = ("confirmed", "fraud", "fraud_times")

    def __init__(self):
        self.confirmed = 0
        self.fraud = 0
        self.fraud_times = deque()


def load_data() -> pd.DataFrame:
    tx_path = DATA_DIR / "train_transaction.csv"
    id_path = DATA_DIR / "train_identity.csv"
    required_tx = {ID_COL, TIME_COL, TARGET, *BASE_RAW_FEATURES}
    required_id = {ID_COL, *BASE_RAW_FEATURES}
    tx = pd.read_csv(tx_path, usecols=lambda c: c in required_tx, low_memory=False)
    identity = pd.read_csv(id_path, usecols=lambda c: c in required_id, low_memory=False)
    return merge_transaction_identity(tx, identity)


def build_feedback(frame: pd.DataFrame, label_eligible: pd.Series) -> pd.DataFrame:
    """Build delayed fraud-feedback features without using validation labels.

    A label is usable only after transaction_time + LABEL_DELAY. Only rows whose
    label_eligible value is True are ever enqueued, so validation labels cannot
    influence any validation prediction.
    """
    working = frame.copy()
    eligible = label_eligible.reindex(working.index).fillna(False).astype(bool)
    working["_eligible"] = eligible
    for name, columns in FEEDBACK_KEYS.items():
        working[f"_key_{name}"] = make_composite_key(working, columns)

    working = working.sort_values(TIME_COL, kind="mergesort")
    index = working.index.to_numpy()
    times = working[TIME_COL].to_numpy(dtype=float)
    labels = working[TARGET].astype(np.int8).to_numpy()
    eligible_arr = working["_eligible"].to_numpy(dtype=bool)
    keys = {
        name: working[f"_key_{name}"].astype("object").to_numpy()
        for name in FEEDBACK_KEYS
    }

    histories = {name: defaultdict(History) for name in FEEDBACK_KEYS}
    pending = deque()
    arrays = {name: np.zeros(len(working), dtype=np.float32) for name in FEEDBACK_FEATURES}
    confidence = np.zeros(len(working), dtype=np.float32)

    start = 0
    while start < len(working):
        now = float(times[start])
        end = start + 1
        while end < len(working) and times[end] == now:
            end += 1

        while pending and pending[0][0] <= now:
            _, original_time, label, stored_keys = pending.popleft()
            for name, key in stored_keys.items():
                if key is None:
                    continue
                h = histories[name][key]
                h.confirmed += 1
                if label == 1:
                    h.fraud += 1
                    h.fraud_times.append(original_time)

        for pos in range(start, end):
            history_channels = 0
            fraud_channels = 0
            total_support = 0
            max_rate = 0.0
            strong_fraud = 0.0

            for name in FEEDBACK_KEYS:
                raw_key = keys[name][pos]
                if pd.isna(raw_key):
                    continue
                h = histories[name].get(str(raw_key))
                if h is None or h.confirmed == 0:
                    continue

                cutoff = now - WINDOW_30D
                while h.fraud_times and h.fraud_times[0] < cutoff:
                    h.fraud_times.popleft()

                rate = h.fraud / h.confirmed
                arrays[f"log_{name}_confirmed_total"][pos] = np.log1p(h.confirmed)
                arrays[f"log_{name}_confirmed_fraud_total"][pos] = np.log1p(h.fraud)
                arrays[f"{name}_confirmed_fraud_rate"][pos] = rate
                arrays[f"log_{name}_confirmed_fraud_30d"][pos] = np.log1p(len(h.fraud_times))
                arrays[f"{name}_has_confirmed_fraud"][pos] = float(h.fraud > 0)

                history_channels += 1
                total_support += h.confirmed
                max_rate = max(max_rate, rate)
                if h.fraud > 0:
                    fraud_channels += 1
                    if name in {"device", "receiver"}:
                        strong_fraud = 1.0

            arrays["feedback_history_channels"][pos] = history_channels
            arrays["confirmed_fraud_channels"][pos] = fraud_channels
            arrays["any_strong_confirmed_fraud"][pos] = strong_fraud
            arrays["max_confirmed_fraud_rate"][pos] = max_rate
            arrays["feedback_total_support_log"][pos] = np.log1p(total_support)

            # Confidence measures support quality, not fraud probability.
            c = 0.10 * min(history_channels, 4)
            for name, weight in (("device", 0.20), ("receiver", 0.20), ("profile", 0.10), ("device_context", 0.10)):
                raw_key = keys[name][pos]
                if pd.isna(raw_key):
                    continue
                h = histories[name].get(str(raw_key))
                if h is not None and h.confirmed > 0:
                    c += weight
            c += 0.20 * min(np.log1p(total_support) / np.log1p(10.0), 1.0)
            confidence[pos] = min(c, 1.0)

        # Current labels are never visible immediately. Only explicitly eligible
        # labels enter the pending queue, and only after the fixed delay.
        for pos in range(start, end):
            if not eligible_arr[pos]:
                continue
            stored = {}
            for name in FEEDBACK_KEYS:
                raw_key = keys[name][pos]
                stored[name] = None if pd.isna(raw_key) else str(raw_key)
            pending.append((now + LABEL_DELAY, now, int(labels[pos]), stored))

        start = end

    out = pd.DataFrame(arrays, index=index)
    out["feedback_confidence"] = confidence
    return out.reindex(frame.index)


def feedback_matrix(frame: pd.DataFrame) -> np.ndarray:
    return frame[FEEDBACK_FEATURES].to_numpy(dtype=np.float32, copy=False)


def fit_specialist(raw: np.ndarray, rel: pd.DataFrame, fb: pd.DataFrame, y: np.ndarray) -> XGBClassifier:
    active = fb["feedback_confidence"].to_numpy(dtype=float) > 0.0
    x = np.hstack([raw, relationship_matrix_v4(rel), feedback_matrix(fb)]).astype(np.float32, copy=False)
    ya = y[active]
    negatives = int((ya == 0).sum())
    positives = int((ya == 1).sum())
    model = XGBClassifier(
        objective="binary:logistic",
        eval_metric="aucpr",
        n_estimators=450,
        learning_rate=0.04,
        max_depth=5,
        min_child_weight=3,
        subsample=0.85,
        colsample_bytree=0.85,
        reg_lambda=1.5,
        reg_alpha=0.1,
        scale_pos_weight=negatives / max(positives, 1),
        tree_method="hist",
        max_bin=128,
        n_jobs=-1,
        random_state=42,
    )
    model.fit(x[active], ya, verbose=False)
    return model


def predict_specialist(model: XGBClassifier, raw: np.ndarray, rel: pd.DataFrame, fb: pd.DataFrame) -> np.ndarray:
    x = np.hstack([raw, relationship_matrix_v4(rel), feedback_matrix(fb)]).astype(np.float32, copy=False)
    return model.predict_proba(x)[:, 1]


def gate_scores(baseline: np.ndarray, specialist: np.ndarray, confidence: np.ndarray, strength: float) -> np.ndarray:
    fused = baseline + strength * confidence * (specialist - baseline)
    fallback = confidence == 0.0
    fused[fallback] = baseline[fallback]
    return np.clip(fused, 0.0, 1.0)


def segment(y: np.ndarray, pred: np.ndarray, mask: np.ndarray) -> dict:
    if not mask.any():
        return {"rows": 0, "frauds": 0, "fraud_rate": 0.0, "recall": 0.0, "precision": 0.0, "fpr": 0.0}
    ys, ps = y[mask], pred[mask]
    tp = int(((ys == 1) & (ps == 1)).sum())
    fp = int(((ys == 0) & (ps == 1)).sum())
    tn = int(((ys == 0) & (ps == 0)).sum())
    frauds = int((ys == 1).sum())
    positives = int((ps == 1).sum())
    return {
        "rows": int(mask.sum()),
        "frauds": frauds,
        "fraud_rate": float(ys.mean()),
        "recall": tp / frauds if frauds else 0.0,
        "precision": tp / positives if positives else 0.0,
        "fpr": fp / (fp + tn) if (fp + tn) else 0.0,
    }


def main():
    print("\n=== LinkRisk v0.5 Delayed Confirmed-Fraud Feedback ===\n")
    print("Only training labels may enter graph memory, after a fixed 72-hour delay.")
    print("Validation labels never influence validation predictions.")
    print("Held-out test remains untouched.\n")

    preprocessor = joblib.load(MODEL_DIR / "baseline_preprocessor.joblib")
    baseline_model = joblib.load(MODEL_DIR / "baseline_xgboost.joblib")
    with (RESULTS_DIR / "baseline_features.json").open("r", encoding="utf-8") as f:
        baseline_features = json.load(f)

    merged = load_data()
    train, validation, test = chronological_split(merged)
    del test
    development = pd.concat([train, validation], axis=0).sort_values(TIME_COL, kind="mergesort")

    print(f"Training rows:   {len(train):,}")
    print(f"Validation rows: {len(validation):,}")
    print("Building causal unlabeled relationship features...")
    rel = build_relationship_features_v4(development)
    rel_train, rel_val = rel.loc[train.index], rel.loc[validation.index]

    print("Building delayed training-label feedback memory...")
    eligible = pd.Series(False, index=development.index)
    eligible.loc[train.index] = True
    fb = build_feedback(development, eligible)
    fb_train, fb_val = fb.loc[train.index], fb.loc[validation.index]

    train_matrix = np.asarray(preprocessor.transform(train[baseline_features]), dtype=np.float32)
    val_matrix = np.asarray(preprocessor.transform(validation[baseline_features]), dtype=np.float32)
    y_train = train[TARGET].astype(np.int8).to_numpy()
    y_val = validation[TARGET].astype(np.int8).to_numpy()

    train_active = fb_train["feedback_confidence"].to_numpy(dtype=float) > 0.0
    print(f"Training feedback-active rows: {int(train_active.sum()):,} ({train_active.mean():.2%})")
    print(f"Training active fraud rate:    {y_train[train_active].mean():.2%}\n")

    print("Training delayed-feedback specialist on active training rows only...")
    specialist_model = fit_specialist(train_matrix, rel_train, fb_train, y_train)

    baseline_scores = baseline_model.predict_proba(val_matrix)[:, 1]
    specialist_scores = predict_specialist(specialist_model, val_matrix, rel_val, fb_val)
    confidence = fb_val["feedback_confidence"].to_numpy(dtype=float)

    baseline_threshold = choose_threshold_for_fpr(y_val, baseline_scores, TARGET_FPR)
    baseline_metrics = evaluate_scores(y_val, baseline_scores, baseline_threshold)
    baseline_pred = (baseline_scores >= baseline_threshold).astype(np.int8)

    print("=== Frozen Baseline ===")
    print(f"Precision: {baseline_metrics['precision']:.4f}")
    print(f"Recall:    {baseline_metrics['recall']:.4f}")
    print(f"PR-AUC:    {baseline_metrics['pr_auc']:.4f}")
    print(f"FPR:       {baseline_metrics['false_positive_rate']:.4%}\n")

    active = confidence > 0.0
    fraud_memory = fb_val["confirmed_fraud_channels"].to_numpy(dtype=float) > 0.0
    strong_fraud = fb_val["any_strong_confirmed_fraud"].to_numpy(dtype=float) > 0.0
    baseline_fn = (y_val == 1) & (baseline_pred == 0)
    reachable = int((baseline_fn & active).sum())

    print("=== Delayed-Feedback Observability ===")
    print(f"Feedback-observable:           {active.mean():.2%}")
    print(f"Prior confirmed-fraud channel: {fraud_memory.mean():.2%}")
    print(f"Strong confirmed-fraud link:   {strong_fraud.mean():.2%}")
    print(f"Mean feedback confidence:      {confidence.mean():.4f}")
    if active.any():
        print(f"Active validation fraud rate:  {y_val[active].mean():.2%}")
    if fraud_memory.any():
        print(f"Fraud-memory fraud rate:       {y_val[fraud_memory].mean():.2%}")
    print(f"Baseline FNs reachable:        {reachable:,} / {baseline_metrics['false_negatives']:,} ({reachable / max(baseline_metrics['false_negatives'], 1):.2%})\n")

    print("=== Predeclared Gate Grid @ <=1% Validation FPR ===")
    print(f"{'gate':>6s} {'threshold':>10s} {'precision':>10s} {'recall':>9s} {'pr_auc':>9s} {'fpr':>9s} {'tp':>6s} {'fp':>6s}")
    print("-" * 82)
    candidates = []
    score_by_gate = {}
    for gate in GATE_GRID:
        fused = gate_scores(baseline_scores, specialist_scores, confidence, gate)
        score_by_gate[gate] = fused
        threshold = choose_threshold_for_fpr(y_val, fused, TARGET_FPR)
        metrics = evaluate_scores(y_val, fused, threshold)
        metrics["gate_strength"] = gate
        candidates.append(metrics)
        print(f"{gate:6.2f} {threshold:10.6f} {metrics['precision']:10.4f} {metrics['recall']:9.4f} {metrics['pr_auc']:9.4f} {metrics['false_positive_rate']:9.4%} {metrics['true_positives']:6d} {metrics['false_positives']:6d}")

    selected = max(candidates, key=lambda m: (m["recall"], m["pr_auc"]))
    selected_scores = score_by_gate[selected["gate_strength"]]
    selected_pred = (selected_scores >= selected["threshold"]).astype(np.int8)
    fallback = confidence == 0.0
    fallback_diff = float(np.max(np.abs(selected_scores[fallback] - baseline_scores[fallback])) if fallback.any() else 0.0)

    recovered_fn = int(((y_val == 1) & (baseline_pred == 0) & (selected_pred == 1)).sum())
    lost_tp = int(((y_val == 1) & (baseline_pred == 1) & (selected_pred == 0)).sum())
    removed_fp = int(((y_val == 0) & (baseline_pred == 1) & (selected_pred == 0)).sum())
    new_fp = int(((y_val == 0) & (baseline_pred == 0) & (selected_pred == 1)).sum())

    print("\n=== Selected v0.5 Development Configuration ===")
    print(f"Gate strength:         {selected['gate_strength']:.2f}")
    print(f"Threshold:             {selected['threshold']:.6f}")
    print(f"Precision:             {selected['precision']:.4f}")
    print(f"Recall:                {selected['recall']:.4f}")
    print(f"PR-AUC:                {selected['pr_auc']:.4f}")
    print(f"FPR:                   {selected['false_positive_rate']:.4%}")
    print(f"TP / FP:               {selected['true_positives']} / {selected['false_positives']}")
    print(f"Recall delta vs ML:    {selected['recall'] - baseline_metrics['recall']:+.4f}")
    print(f"PR-AUC delta vs ML:    {selected['pr_auc'] - baseline_metrics['pr_auc']:+.4f}")
    print(f"Exact fallback check:  {fallback_diff:.12f}\n")

    print("=== Decision Transitions vs Baseline ===")
    print(f"Recovered baseline FNs: {recovered_fn}")
    print(f"Lost baseline TPs:       {lost_tp}")
    print(f"Removed baseline FPs:    {removed_fp}")
    print(f"New false positives:     {new_fp}\n")

    print("=== Feedback-Defined Segment Results ===")
    segments = {}
    for label, mask in (("feedback-observable", active), ("confirmed-fraud-channel", fraud_memory), ("strong-confirmed-fraud", strong_fraud)):
        base = segment(y_val, baseline_pred, mask)
        link = segment(y_val, selected_pred, mask)
        segments[label] = {"baseline": base, "linkrisk": link}
        print(f"{label}:")
        print(f"  rows={base['rows']:,} frauds={base['frauds']:,} fraud_rate={base['fraud_rate']:.2%}")
        print(f"  baseline recall={base['recall']:.2%} precision={base['precision']:.2%} FPR={base['fpr']:.2%}")
        print(f"  LinkRisk recall={link['recall']:.2%} precision={link['precision']:.2%} FPR={link['fpr']:.2%}")

    importances = specialist_model.feature_importances_[-len(FEEDBACK_FEATURES):]
    feedback_importance = dict(zip(FEEDBACK_FEATURES, map(float, importances)))
    print("\n=== Top Delayed-Feedback Features ===")
    for name, value in sorted(feedback_importance.items(), key=lambda item: item[1], reverse=True)[:12]:
        print(f"{name:42s} {value:.5f}")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(specialist_model, MODEL_DIR / "feedback_specialist_v5.joblib")
    result = {
        "experiment": "linkrisk_delayed_feedback_v0.5",
        "test_evaluated": False,
        "label_delay_seconds": LABEL_DELAY,
        "validation_labels_used_as_feedback": False,
        "baseline": baseline_metrics,
        "gate_grid": candidates,
        "selected": selected,
        "feedback_observable": float(active.mean()),
        "confirmed_fraud_channel": float(fraud_memory.mean()),
        "strong_confirmed_fraud": float(strong_fraud.mean()),
        "reachable_baseline_false_negatives": reachable,
        "transitions": {
            "recovered_false_negatives": recovered_fn,
            "lost_true_positives": lost_tp,
            "removed_false_positives": removed_fp,
            "new_false_positives": new_fp,
        },
        "segments": segments,
        "feedback_feature_importance": feedback_importance,
        "exact_fallback_max_abs_difference": fallback_diff,
    }
    with (RESULTS_DIR / "feedback_v5_validation.json").open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print("\nSaved artifacts/models/feedback_specialist_v5.joblib")
    print("Saved artifacts/results/feedback_v5_validation.json")
    print("Held-out test remains untouched.\n")


if __name__ == "__main__":
    main()
