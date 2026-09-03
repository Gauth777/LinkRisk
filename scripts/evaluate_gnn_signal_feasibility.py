from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score

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
MODEL_DIR = ROOT / "artifacts" / "models"
RESULTS_DIR = ROOT / "artifacts" / "results"
OUT = RESULTS_DIR / "gnn_signal_feasibility.json"


def load_data() -> pd.DataFrame:
    tx_path = DATA_DIR / "train_transaction.csv"
    id_path = DATA_DIR / "train_identity.csv"
    required_tx = {ID_COL, TIME_COL, TARGET, *BASE_RAW_FEATURES}
    required_id = {ID_COL, *BASE_RAW_FEATURES}
    tx = pd.read_csv(tx_path, usecols=lambda c: c in required_tx, low_memory=False)
    identity = pd.read_csv(id_path, usecols=lambda c: c in required_id, low_memory=False)
    return merge_transaction_identity(tx, identity)


def _valid_token(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "unknown", "__missing__"}:
        return None
    return text


def _composite_token(row: pd.Series, columns: list[str]) -> str | None:
    parts: list[str] = []
    present = False
    for column in columns:
        token = _valid_token(row.get(column))
        if token is None:
            parts.append("_")
        else:
            parts.append(token)
            present = True
    return "|".join(parts) if present else None


def build_relation(values: list[str | None]):
    import torch

    mapping: dict[str, int] = {}
    src: list[int] = []
    dst: list[int] = []
    degree: list[int] = []
    for tx_index, token in enumerate(values):
        if token is None:
            continue
        entity_index = mapping.get(token)
        if entity_index is None:
            entity_index = len(mapping)
            mapping[token] = entity_index
            degree.append(0)
        src.append(tx_index)
        dst.append(entity_index)
        degree[entity_index] += 1

    if not src:
        return None, None, mapping

    edge_index = torch.tensor([src, dst], dtype=torch.long)
    degree_array = np.asarray(degree, dtype=np.float32)
    entity_x = torch.from_numpy(
        np.column_stack(
            [
                np.log1p(degree_array),
                np.ones_like(degree_array),
            ]
        ).astype(np.float32)
    )
    return edge_index, entity_x, mapping


def score_baseline_same_slice(
    frame: pd.DataFrame,
    tune_start: int,
    val_start: int,
    target_fpr: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    preprocessor = joblib.load(MODEL_DIR / "baseline_preprocessor.joblib")
    model = joblib.load(MODEL_DIR / "baseline_xgboost.joblib")
    features = select_baseline_features(frame)
    matrix = preprocessor.transform(frame[features])
    scores = model.predict_proba(matrix)[:, 1]

    tune_y = frame.iloc[tune_start:val_start][TARGET].astype(np.int8).to_numpy()
    tune_scores = scores[tune_start:val_start]
    threshold = choose_threshold_for_fpr(tune_y, tune_scores, target_fpr=target_fpr)
    tune_metrics = evaluate_scores(tune_y, tune_scores, threshold)

    val_y = frame.iloc[val_start:][TARGET].astype(np.int8).to_numpy()
    val_metrics = evaluate_scores(val_y, scores[val_start:], threshold)
    return tune_metrics, val_metrics


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "GPU-oriented heterogeneous GraphSAGE signal test. This is explicitly "
            "transductive development feasibility, not a deployment-valid evaluation."
        )
    )
    parser.add_argument("--train-rows", type=int, default=120_000, help="Most recent historical-train rows included in the graph.")
    parser.add_argument("--validation-rows", type=int, default=30_000, help="Earliest development-validation rows included in the graph.")
    parser.add_argument("--tune-frac", type=float, default=0.15, help="Chronological tail of sampled train used for early stopping/thresholding.")
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--hidden-dim", type=int, default=64)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--target-fpr", type=float, default=0.01)
    args = parser.parse_args()

    try:
        import torch
        import torch.nn.functional as F
        from torch_geometric.data import HeteroData
        from torch_geometric.nn import HeteroConv, SAGEConv
    except ImportError as exc:
        raise SystemExit(
            "PyTorch/PyG is not installed. Run this experiment on Colab/GPU. Install "
            "PyTorch for the active CUDA runtime, then `pip install torch_geometric`."
        ) from exc

    if not (0.05 <= args.tune_frac <= 0.4):
        raise SystemExit("--tune-frac must be between 0.05 and 0.40")

    print("=== LinkRisk GNN Structural-Signal Feasibility ===\n")
    print("DEVELOPMENT SIGNAL TEST ONLY — NOT DEPLOYMENT-VALID.")
    print("This first pass is transductive: validation transaction structure is present in the graph,")
    print("although validation fraud labels are excluded from training. A positive result must be causalized\n")

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
    tune_start = fit_rows

    print(f"Graph train rows      : {len(sampled_train):,} ({fit_rows:,} fit / {tune_rows:,} tune)")
    print(f"Graph validation rows : {len(sampled_validation):,}")
    print(f"Old final rows        : {old_final_rows:,} (not included)\n")

    preprocessor = joblib.load(MODEL_DIR / "baseline_preprocessor.joblib")
    features = select_baseline_features(frame)
    tx_matrix = preprocessor.transform(frame[features])
    if hasattr(tx_matrix, "toarray"):
        tx_matrix = tx_matrix.toarray()
    tx_matrix = np.asarray(tx_matrix, dtype=np.float32)

    # Normalize only from the fit prefix. Missing/inf values become zero after scaling.
    fit_matrix = tx_matrix[:fit_rows]
    means = np.nanmean(fit_matrix, axis=0)
    stds = np.nanstd(fit_matrix, axis=0)
    stds = np.where(stds < 1e-6, 1.0, stds)
    tx_matrix = (tx_matrix - means) / stds
    tx_matrix = np.nan_to_num(tx_matrix, nan=0.0, posinf=10.0, neginf=-10.0)
    tx_matrix = np.clip(tx_matrix, -10.0, 10.0).astype(np.float32)

    relation_values: dict[str, list[str | None]] = {
        "card_profile": [
            _composite_token(row, ["card1", "card2", "card3", "card4", "card5", "card6"])
            for _, row in frame.iterrows()
        ],
        "device_context": [_valid_token(value) for value in frame.get("DeviceInfo", pd.Series([None] * len(frame)))],
        "payer_domain": [_valid_token(value) for value in frame.get("P_emaildomain", pd.Series([None] * len(frame)))],
        "recipient_domain": [_valid_token(value) for value in frame.get("R_emaildomain", pd.Series([None] * len(frame)))],
        "address_context": [
            _composite_token(row, ["addr1", "addr2"])
            for _, row in frame.iterrows()
        ],
    }

    data = HeteroData()
    data["transaction"].x = torch.from_numpy(tx_matrix)
    labels = torch.from_numpy(frame[TARGET].astype(np.float32).to_numpy())
    data["transaction"].y = labels

    relation_metadata: dict[str, Any] = {}
    for entity_type, values in relation_values.items():
        edge_index, entity_x, mapping = build_relation(values)
        if edge_index is None or entity_x is None:
            continue
        data[entity_type].x = entity_x
        data[("transaction", f"has_{entity_type}", entity_type)].edge_index = edge_index
        data[(entity_type, f"rev_has_{entity_type}", "transaction")].edge_index = edge_index.flip(0)
        relation_metadata[entity_type] = {
            "entities": len(mapping),
            "edges": int(edge_index.shape[1]),
        }

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device                : {device}")
    for name, meta in relation_metadata.items():
        print(f"  {name:18s}: {meta['entities']:,} entities / {meta['edges']:,} edges")
    print()

    class HeteroGraphSAGE(torch.nn.Module):
        def __init__(self, metadata, hidden_dim: int):
            super().__init__()
            edge_types = metadata[1]
            self.conv1 = HeteroConv(
                {edge_type: SAGEConv((-1, -1), hidden_dim) for edge_type in edge_types},
                aggr="sum",
            )
            self.conv2 = HeteroConv(
                {edge_type: SAGEConv((-1, -1), hidden_dim) for edge_type in edge_types},
                aggr="sum",
            )
            self.head = torch.nn.Linear(hidden_dim, 1)

        def forward(self, x_dict, edge_index_dict):
            x_dict = self.conv1(x_dict, edge_index_dict)
            x_dict = {key: F.relu(value) for key, value in x_dict.items()}
            x_dict = self.conv2(x_dict, edge_index_dict)
            x_dict = {key: F.relu(value) for key, value in x_dict.items()}
            return self.head(x_dict["transaction"]).squeeze(-1)

    data = data.to(device)
    model = HeteroGraphSAGE(data.metadata(), args.hidden_dim).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)

    fit_index = torch.arange(0, fit_rows, device=device)
    tune_index = torch.arange(tune_start, val_start, device=device)
    val_index = torch.arange(val_start, len(frame), device=device)
    fit_y = data["transaction"].y[fit_index]
    positives = float((fit_y == 1).sum().item())
    negatives = float((fit_y == 0).sum().item())
    pos_weight = torch.tensor([negatives / max(positives, 1.0)], device=device)
    criterion = torch.nn.BCEWithLogitsLoss(pos_weight=pos_weight)

    best_ap = -1.0
    best_state = None
    patience = 4
    stale = 0

    for epoch in range(1, args.epochs + 1):
        model.train()
        optimizer.zero_grad(set_to_none=True)
        logits = model(data.x_dict, data.edge_index_dict)
        loss = criterion(logits[fit_index], data["transaction"].y[fit_index])
        loss.backward()
        optimizer.step()

        model.eval()
        with torch.no_grad():
            eval_logits = model(data.x_dict, data.edge_index_dict)
            tune_scores = torch.sigmoid(eval_logits[tune_index]).detach().cpu().numpy()
        tune_y_np = frame.iloc[tune_start:val_start][TARGET].astype(np.int8).to_numpy()
        tune_ap = float(average_precision_score(tune_y_np, tune_scores))
        print(f"epoch {epoch:02d}  loss={loss.item():.5f}  tune_PR-AUC={tune_ap:.5f}")

        if tune_ap > best_ap + 1e-5:
            best_ap = tune_ap
            best_state = copy.deepcopy(model.state_dict())
            stale = 0
        else:
            stale += 1
            if stale >= patience:
                print("early stop")
                break

    if best_state is None:
        raise RuntimeError("GNN training did not produce a checkpoint")
    model.load_state_dict(best_state)
    model.eval()

    with torch.no_grad():
        logits = model(data.x_dict, data.edge_index_dict)
        tune_scores = torch.sigmoid(logits[tune_index]).cpu().numpy()
        validation_scores = torch.sigmoid(logits[val_index]).cpu().numpy()

    tune_y_np = frame.iloc[tune_start:val_start][TARGET].astype(np.int8).to_numpy()
    val_y_np = frame.iloc[val_start:][TARGET].astype(np.int8).to_numpy()
    threshold = choose_threshold_for_fpr(tune_y_np, tune_scores, target_fpr=args.target_fpr)
    gnn_tune = evaluate_scores(tune_y_np, tune_scores, threshold)
    gnn_validation = evaluate_scores(val_y_np, validation_scores, threshold)

    baseline_tune, baseline_validation = score_baseline_same_slice(
        frame,
        tune_start=tune_start,
        val_start=val_start,
        target_fpr=args.target_fpr,
    )

    payload = {
        "experiment": "heterogeneous_graphsage_structural_signal_feasibility",
        "status": "development_signal_only_transductive_not_deployment_valid",
        "scientific_boundary": {
            "old_final_test_rows": old_final_rows,
            "old_final_test_in_graph": False,
            "old_final_test_labels_used": False,
            "validation_labels_used_for_training": False,
            "validation_structure_present_during_message_passing": True,
            "warning": (
                "This is a transductive structural-signal test. Future validation structure can influence "
                "embeddings, so these metrics must not be presented as live/causal performance."
            ),
        },
        "sample": {
            "historical_train_rows": len(sampled_train),
            "fit_rows": fit_rows,
            "internal_tune_rows": tune_rows,
            "validation_rows": len(sampled_validation),
            "relations": relation_metadata,
        },
        "configuration": {
            "hidden_dim": args.hidden_dim,
            "epochs_requested": args.epochs,
            "learning_rate": args.lr,
            "target_fpr": args.target_fpr,
            "device": str(device),
        },
        "gnn_internal_tune": gnn_tune,
        "gnn_development_validation": gnn_validation,
        "baseline_same_slice_internal_tune": baseline_tune,
        "baseline_same_slice_validation": baseline_validation,
        "delta_gnn_vs_baseline_same_slice": {
            "pr_auc": gnn_validation["pr_auc"] - baseline_validation["pr_auc"],
            "recall_pp": 100.0 * (gnn_validation["recall"] - baseline_validation["recall"]),
            "precision_pp": 100.0 * (gnn_validation["precision"] - baseline_validation["precision"]),
            "fpr_pp": 100.0 * (gnn_validation["false_positive_rate"] - baseline_validation["false_positive_rate"]),
        },
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)

    print("\n=== GNN SIGNAL RESULT ===")
    print(f"GNN PR-AUC      : {gnn_validation['pr_auc']:.4f}")
    print(f"Baseline PR-AUC : {baseline_validation['pr_auc']:.4f}")
    print(f"Delta PR-AUC    : {payload['delta_gnn_vs_baseline_same_slice']['pr_auc']:+.4f}")
    print(f"GNN recall      : {gnn_validation['recall']:.4f}")
    print(f"Baseline recall : {baseline_validation['recall']:.4f}")
    print(f"Saved {OUT.relative_to(ROOT)}")
    print("If this shows meaningful lift, the next step is a causal temporal/inductive GNN evaluation.")


if __name__ == "__main__":
    main()
