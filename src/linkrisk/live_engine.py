from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Any, Mapping

import numpy as np
import pandas as pd

from linkrisk.baseline import BASE_RAW_FEATURES, ID_COL, TARGET, TIME_COL
from linkrisk.engine import FrozenChampionScorer
from linkrisk.feedback_features_v5 import (
    FEEDBACK_KEYS_V5,
    LABEL_DELAY_SECONDS,
    build_feedback_features_v5,
)
from linkrisk.relationship_features_v4 import (
    build_relationship_features_v4,
    make_composite_key,
)


@dataclass(frozen=True)
class LiveTransactionInput:
    amount: float
    payment_profile: str
    device_info: str
    receiver_domain: str
    browser_context: str
    product_code: str = "W"
    payer_domain: str = "gmail.com"
    device_type: str = "desktop"
    card_network: str = "visa"
    card_type: str = "debit"


@dataclass
class Adjudication:
    outcome: str
    recorded_at: float


def _stable_bucket(identifier: str, salt: str, low: int, high: int) -> int:
    if high < low:
        raise ValueError("high must be >= low")
    payload = f"{salt}|{identifier}".encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    value = int.from_bytes(digest[:8], "big")
    return low + (value % (high - low + 1))


def live_input_to_model_row(
    event: LiveTransactionInput,
    *,
    transaction_id: str,
    transaction_time: float,
) -> dict[str, Any]:
    """Map human-facing simulator inputs into an IEEE-CIS-compatible row.

    The stable payment-profile mapping is a demo adapter. It does not claim that
    masked IEEE fields are literal customer/account IDs; it simply keeps repeated
    simulator profile identifiers internally consistent so the validated
    relationship logic can operate on live events.
    """
    row: dict[str, Any] = {column: np.nan for column in BASE_RAW_FEATURES}
    profile = event.payment_profile.strip() or "PROFILE-UNKNOWN"

    row.update(
        {
            ID_COL: transaction_id,
            TIME_COL: float(transaction_time),
            TARGET: 0,
            "TransactionAmt": float(event.amount),
            "ProductCD": event.product_code,
            "card1": _stable_bucket(profile, "card1", 1000, 18000),
            "card2": _stable_bucket(profile, "card2", 100, 600),
            "card3": _stable_bucket(profile, "card3", 100, 230),
            "card4": event.card_network,
            "card5": _stable_bucket(profile, "card5", 100, 235),
            "card6": event.card_type,
            "addr1": _stable_bucket(profile, "addr1", 100, 520),
            "P_emaildomain": event.payer_domain,
            "R_emaildomain": event.receiver_domain,
            "DeviceType": event.device_type,
            "DeviceInfo": event.device_info,
            "id_31": event.browser_context,
        }
    )
    return row


def _channel_keys(frame: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        name: make_composite_key(frame, columns)
        for name, columns in FEEDBACK_KEYS_V5.items()
    }


class LiveLinkRiskEngine:
    """Stateful demo runtime around the frozen LinkRisk v0.5 champion.

    For each incoming payment this engine recomputes the exact causal v4
    relationship features and v5 delayed-feedback features over session history,
    then calls the frozen baseline/specialist/gate/policy runtime. It is designed
    for interactive sessions, not high-throughput production serving.
    """

    def __init__(
        self,
        scorer: FrozenChampionScorer,
        *,
        start_time: float = 0.0,
    ) -> None:
        self.scorer = scorer
        self.clock = float(start_time)
        self._rows: list[dict[str, Any]] = []
        self._records: dict[str, dict[str, Any]] = {}
        self._adjudications: dict[str, Adjudication] = {}
        self._sequence = 1

    @property
    def transaction_ids(self) -> list[str]:
        return [str(row[ID_COL]) for row in self._rows]

    def reset(self, *, start_time: float = 0.0) -> None:
        self.clock = float(start_time)
        self._rows.clear()
        self._records.clear()
        self._adjudications.clear()
        self._sequence = 1

    def advance_time(self, seconds: float) -> None:
        seconds = float(seconds)
        if seconds < 0:
            raise ValueError("Cannot move simulation time backwards")
        self.clock += seconds

    def next_transaction_id(self) -> str:
        while True:
            candidate = f"TX-{self._sequence:04d}"
            self._sequence += 1
            if candidate not in self._records:
                return candidate

    def _history_frame(
        self,
        current_row: Mapping[str, Any] | None = None,
    ) -> pd.DataFrame:
        rows = [dict(row) for row in self._rows]
        if current_row is not None:
            rows.append(dict(current_row))
        if not rows:
            return pd.DataFrame()

        for row in rows:
            tx_id = str(row[ID_COL])
            adjudication = self._adjudications.get(tx_id)
            row[TARGET] = 1 if adjudication and adjudication.outcome == "fraud" else 0

        frame = pd.DataFrame(rows)
        frame.index = frame[ID_COL].astype(str)
        return frame

    def _label_eligibility(
        self,
        frame: pd.DataFrame,
        current_id: str,
    ) -> pd.Series:
        eligible = pd.Series(False, index=frame.index, dtype=bool)
        for tx_id, adjudication in self._adjudications.items():
            if tx_id == current_id or tx_id not in eligible.index:
                continue
            if adjudication.recorded_at <= self.clock:
                eligible.loc[tx_id] = True
        return eligible

    def score_event(
        self,
        event: LiveTransactionInput,
        *,
        transaction_id: str | None = None,
    ) -> dict[str, Any]:
        tx_id = transaction_id or self.next_transaction_id()
        if tx_id in self._records:
            raise ValueError(f"Duplicate transaction id: {tx_id}")

        current_row = live_input_to_model_row(
            event,
            transaction_id=tx_id,
            transaction_time=self.clock,
        )
        frame = self._history_frame(current_row)
        eligibility = self._label_eligibility(frame, tx_id)

        relationship = build_relationship_features_v4(frame)
        feedback = build_feedback_features_v5(frame, eligibility)

        scored = self.scorer.score_batch(
            frame.loc[[tx_id]],
            relationship.loc[[tx_id]],
            feedback.loc[[tx_id]],
        )
        decision = scored.loc[tx_id].to_dict()

        network = self._build_network_snapshot(frame, tx_id)
        record = {
            "transaction_id": tx_id,
            "transaction_time": float(self.clock),
            "input": event,
            "raw": dict(current_row),
            "decision": decision,
            "relationship_features": relationship.loc[tx_id].to_dict(),
            "feedback_features": feedback.loc[tx_id].to_dict(),
            "network": network,
        }

        self._rows.append(dict(current_row))
        self._records[tx_id] = record
        return record

    def adjudicate(self, transaction_id: str, outcome: str) -> None:
        if transaction_id not in self._records:
            raise KeyError(f"Unknown transaction: {transaction_id}")
        normalized = outcome.strip().lower()
        if normalized not in {"fraud", "legitimate"}:
            raise ValueError("outcome must be 'fraud' or 'legitimate'")
        self._adjudications[transaction_id] = Adjudication(
            outcome=normalized,
            recorded_at=float(self.clock),
        )

    def clear_adjudication(self, transaction_id: str) -> None:
        self._adjudications.pop(transaction_id, None)

    def adjudication_status(self, transaction_id: str) -> dict[str, Any]:
        if transaction_id not in self._records:
            raise KeyError(f"Unknown transaction: {transaction_id}")
        adjudication = self._adjudications.get(transaction_id)
        if adjudication is None:
            return {
                "outcome": None,
                "state": "unadjudicated",
                "available_at": None,
                "seconds_remaining": None,
            }

        tx_time = float(self._records[transaction_id]["transaction_time"])
        available_at = max(
            tx_time + LABEL_DELAY_SECONDS,
            adjudication.recorded_at,
        )
        remaining = max(available_at - self.clock, 0.0)
        return {
            "outcome": adjudication.outcome,
            "state": "matured" if remaining <= 0.0 else "pending",
            "available_at": available_at,
            "seconds_remaining": remaining,
        }

    def get_record(self, transaction_id: str) -> dict[str, Any]:
        if transaction_id not in self._records:
            raise KeyError(f"Unknown transaction: {transaction_id}")
        record = dict(self._records[transaction_id])
        record["adjudication"] = self.adjudication_status(transaction_id)
        return record

    def feed(self) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        for tx_id in self.transaction_ids:
            record = self._records[tx_id]
            decision = record["decision"]
            status = self.adjudication_status(tx_id)
            event: LiveTransactionInput = record["input"]
            rows.append(
                {
                    "Transaction": tx_id,
                    "Time": format_sim_time(record["transaction_time"]),
                    "Amount": event.amount,
                    "Profile": event.payment_profile,
                    "Device": event.device_info,
                    "Baseline": float(decision["baseline_risk"]),
                    "LinkRisk": float(decision["linkrisk_risk"]),
                    "Confidence": float(decision["graph_confidence"]),
                    "Action": decision["action"],
                    "Outcome": format_adjudication_status(status),
                }
            )
        return pd.DataFrame(rows)

    def _build_network_snapshot(
        self,
        frame: pd.DataFrame,
        current_id: str,
        *,
        max_prior_per_channel: int = 5,
    ) -> dict[str, Any]:
        current_time = float(frame.loc[current_id, TIME_COL])
        prior = frame[frame[TIME_COL].astype(float) < current_time]
        nodes: dict[str, dict[str, Any]] = {
            f"tx:{current_id}": {
                "id": f"tx:{current_id}",
                "label": current_id,
                "kind": "current",
                "detail": "Current transaction",
            }
        }
        edges: list[dict[str, str]] = []

        if prior.empty:
            return {"nodes": list(nodes.values()), "edges": edges}

        all_keys = _channel_keys(frame)
        channel_labels = {
            "profile": "Payment profile",
            "device": "Strong device view",
            "receiver": "Receiver-domain view",
            "device_context": "Device/browser context",
        }

        for channel, series in all_keys.items():
            current_key = series.loc[current_id]
            if pd.isna(current_key):
                continue

            matching_ids = [
                str(idx)
                for idx in prior.index
                if not pd.isna(series.loc[idx])
                and str(series.loc[idx]) == str(current_key)
            ]
            if not matching_ids:
                continue

            matching_ids = matching_ids[-max_prior_per_channel:]
            relation_id = f"rel:{channel}"
            nodes[relation_id] = {
                "id": relation_id,
                "label": channel_labels[channel],
                "kind": "relation",
                "detail": f"Shared {channel_labels[channel].lower()}",
            }
            edges.append({"source": f"tx:{current_id}", "target": relation_id})

            for prior_id in matching_ids:
                tx_node_id = f"tx:{prior_id}"
                status = self._snapshot_prior_status(
                    prior_id,
                    as_of=current_time,
                )
                if tx_node_id not in nodes:
                    nodes[tx_node_id] = {
                        "id": tx_node_id,
                        "label": prior_id,
                        "kind": status["kind"],
                        "detail": status["detail"],
                    }
                edges.append({"source": relation_id, "target": tx_node_id})

        return {"nodes": list(nodes.values()), "edges": edges}

    def _snapshot_prior_status(
        self,
        transaction_id: str,
        *,
        as_of: float,
    ) -> dict[str, str]:
        adjudication = self._adjudications.get(transaction_id)
        if adjudication is None or adjudication.recorded_at > as_of:
            return {
                "kind": "prior",
                "detail": "Prior transaction; no adjudicated outcome was available",
            }

        tx_time = float(self._records[transaction_id]["transaction_time"])
        available_at = max(tx_time + LABEL_DELAY_SECONDS, adjudication.recorded_at)
        if available_at > as_of:
            return {
                "kind": "pending",
                "detail": f"{adjudication.outcome.title()} outcome recorded but not yet matured",
            }
        if adjudication.outcome == "fraud":
            return {
                "kind": "fraud",
                "detail": "Matured confirmed-fraud feedback",
            }
        return {
            "kind": "legitimate",
            "detail": "Matured confirmed-legitimate feedback",
        }


def format_sim_time(seconds: float) -> str:
    total = max(int(seconds), 0)
    day = total // 86400 + 1
    within = total % 86400
    hour = within // 3600
    minute = (within % 3600) // 60
    return f"Day {day} {hour:02d}:{minute:02d}"


def format_adjudication_status(status: Mapping[str, Any]) -> str:
    if status["state"] == "unadjudicated":
        return "Pending"
    label = "Fraud" if status["outcome"] == "fraud" else "Legitimate"
    if status["state"] == "matured":
        return f"{label} · matured"
    hours = math.ceil(float(status["seconds_remaining"]) / 3600.0)
    return f"{label} · matures in {hours}h"
