from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    precision_score,
    recall_score,
    roc_curve,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder
from xgboost import XGBClassifier


TARGET = "isFraud"
TIME_COL = "TransactionDT"
ID_COL = "TransactionID"

BASE_RAW_FEATURES = [
    "TransactionAmt",
    "ProductCD",
    "card1",
    "card2",
    "card3",
    "card4",
    "card5",
    "card6",
    "addr1",
    "addr2",
    "dist1",
    "dist2",
    "P_emaildomain",
    "R_emaildomain",
]
BASE_RAW_FEATURES += [f"M{i}" for i in range(1, 10)]
BASE_RAW_FEATURES += [f"id_{i:02d}" for i in range(1, 39)]
BASE_RAW_FEATURES += ["DeviceType", "DeviceInfo"]


@dataclass
class BaselineArtifacts:
    preprocessor: ColumnTransformer
    model: XGBClassifier
    feature_columns: list[str]
    threshold: float
    metrics: dict


def merge_transaction_identity(
    transactions: pd.DataFrame,
    identity: pd.DataFrame,
) -> pd.DataFrame:
    if ID_COL not in transactions.columns or ID_COL not in identity.columns:
        raise KeyError("TransactionID must exist in both IEEE-CIS tables")

    merged = transactions.merge(identity, on=ID_COL, how="left", validate="one_to_one")
    return merged


def select_baseline_features(df: pd.DataFrame) -> list[str]:
    """
    Return the frozen point-in-time baseline feature set.

    Deliberately excluded:
      - TransactionID: identifier, not a predictive feature
      - TransactionDT: used for chronological splitting, not as a direct predictor
      - C*: pre-computed count/history features
      - D*: historical/time-delta features
      - V*: Vesta engineered features, many relation/count based

    M*, raw card/address/email, amount/product and identity/device columns remain.
    """
    return [column for column in BASE_RAW_FEATURES if column in df.columns]


def build_preprocessor(train_x: pd.DataFrame) -> ColumnTransformer:
    categorical_columns = [
        column
        for column in train_x.columns
        if train_x[column].dtype == "object" or str(train_x[column].dtype).startswith("category")
    ]
    numeric_columns = [column for column in train_x.columns if column not in categorical_columns]

    categorical_pipeline = Pipeline(
        steps=[
            (
                "imputer",
                SimpleImputer(strategy="constant", fill_value="__MISSING__"),
            ),
            (
                "encoder",
                OrdinalEncoder(
                    handle_unknown="use_encoded_value",
                    unknown_value=-1,
                    dtype=np.float32,
                ),
            ),
        ]
    )

    preprocessor = ColumnTransformer(
        transformers=[
            ("numeric", "passthrough", numeric_columns),
            ("categorical", categorical_pipeline, categorical_columns),
        ],
        remainder="drop",
        verbose_feature_names_out=False,
    )
    return preprocessor


def choose_threshold_for_fpr(
    y_true: np.ndarray,
    scores: np.ndarray,
    target_fpr: float = 0.01,
) -> float:
    """
    Pick the threshold that gives the highest recall while keeping validation
    false-positive rate at or below target_fpr.

    This makes our operating point explicit instead of treating 0.5 as sacred.
    """
    fpr, tpr, thresholds = roc_curve(y_true, scores)
    valid = np.where(fpr <= target_fpr)[0]
    if len(valid) == 0:
        return 1.0

    # Among thresholds satisfying the FPR budget, choose the one with max recall/TPR.
    best_index = valid[np.argmax(tpr[valid])]
    threshold = thresholds[best_index]

    if not np.isfinite(threshold):
        return 1.0
    return float(threshold)


def evaluate_scores(
    y_true: np.ndarray,
    scores: np.ndarray,
    threshold: float,
) -> dict:
    predictions = (scores >= threshold).astype(np.int8)
    tn, fp, fn, tp = confusion_matrix(y_true, predictions, labels=[0, 1]).ravel()

    fpr = fp / (fp + tn) if (fp + tn) else 0.0

    return {
        "threshold": float(threshold),
        "precision": float(precision_score(y_true, predictions, zero_division=0)),
        "recall": float(recall_score(y_true, predictions, zero_division=0)),
        "pr_auc": float(average_precision_score(y_true, scores)),
        "false_positive_rate": float(fpr),
        "true_positives": int(tp),
        "false_positives": int(fp),
        "true_negatives": int(tn),
        "false_negatives": int(fn),
    }


def train_xgboost_baseline(
    train_df: pd.DataFrame,
    validation_df: pd.DataFrame,
    target_fpr: float = 0.01,
) -> BaselineArtifacts:
    feature_columns = select_baseline_features(train_df)
    if not feature_columns:
        raise ValueError("No baseline features were found")

    train_x = train_df[feature_columns]
    val_x = validation_df[feature_columns]
    train_y = train_df[TARGET].astype(np.int8).to_numpy()
    val_y = validation_df[TARGET].astype(np.int8).to_numpy()

    preprocessor = build_preprocessor(train_x)
    train_matrix = preprocessor.fit_transform(train_x)
    val_matrix = preprocessor.transform(val_x)

    negatives = int((train_y == 0).sum())
    positives = int((train_y == 1).sum())
    scale_pos_weight = negatives / max(positives, 1)

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
        scale_pos_weight=scale_pos_weight,
        tree_method="hist",
        n_jobs=-1,
        random_state=42,
    )

    model.fit(
        train_matrix,
        train_y,
        eval_set=[(val_matrix, val_y)],
        verbose=False,
    )

    validation_scores = model.predict_proba(val_matrix)[:, 1]
    threshold = choose_threshold_for_fpr(
        val_y,
        validation_scores,
        target_fpr=target_fpr,
    )
    metrics = evaluate_scores(val_y, validation_scores, threshold)
    metrics["target_fpr_budget"] = float(target_fpr)
    metrics["scale_pos_weight"] = float(scale_pos_weight)
    metrics["feature_count"] = len(feature_columns)

    return BaselineArtifacts(
        preprocessor=preprocessor,
        model=model,
        feature_columns=feature_columns,
        threshold=threshold,
        metrics=metrics,
    )


def save_baseline_artifacts(
    artifacts: BaselineArtifacts,
    output_dir: str | Path,
) -> None:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    joblib.dump(artifacts.preprocessor, output_dir / "baseline_preprocessor.joblib")
    joblib.dump(artifacts.model, output_dir / "baseline_xgboost.joblib")
