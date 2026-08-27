"""Durable local session journal for the LinkRisk demo runtime.

The live engine remains the source of truth for scoring. This module persists the
minimal sequence of causal inputs needed to deterministically replay the session
on FastAPI restart. It deliberately does not pickle model/runtime internals.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
import os
from pathlib import Path
from threading import Lock
from typing import Any, Mapping

from linkrisk.live_engine import LiveTransactionInput


SCHEMA_VERSION = 1


class SessionStoreError(RuntimeError):
    """Raised when the local session journal cannot be read or written safely."""


def default_session_path(root: Path) -> Path:
    configured = os.getenv("LINKRISK_SESSION_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return root / ".linkrisk" / "session.jsonl"


class LocalSessionStore:
    """Append-only JSONL journal for one local LinkRisk demonstration session."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = Lock()

    def _append(self, event_type: str, payload: Mapping[str, Any]) -> None:
        event = {
            "version": SCHEMA_VERSION,
            "type": event_type,
            "payload": dict(payload),
        }
        line = json.dumps(event, separators=(",", ":"), sort_keys=True)
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(line + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
        except OSError as exc:
            raise SessionStoreError(f"Could not persist LinkRisk session: {exc}") from exc

    def append_transaction(self, record: Mapping[str, Any]) -> None:
        event = record.get("input")
        if is_dataclass(event):
            input_payload = asdict(event)
        elif isinstance(event, Mapping):
            input_payload = dict(event)
        else:
            raise SessionStoreError("Transaction record has no serialisable input payload")

        integration = record.get("integration")
        self._append(
            "transaction",
            {
                "transaction_id": str(record["transaction_id"]),
                "transaction_time": float(record["transaction_time"]),
                "input": input_payload,
                "integration": dict(integration) if isinstance(integration, Mapping) else None,
            },
        )

    def append_adjudication(self, transaction_id: str, outcome: str, recorded_at: float) -> None:
        self._append(
            "adjudication",
            {
                "transaction_id": transaction_id,
                "outcome": outcome.strip().lower(),
                "recorded_at": float(recorded_at),
            },
        )

    def append_clear_adjudication(self, transaction_id: str) -> None:
        self._append("clear_adjudication", {"transaction_id": transaction_id})

    def append_clock(self, clock: float) -> None:
        self._append("clock", {"clock": float(clock)})

    def events(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            with self._lock:
                lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise SessionStoreError(f"Could not read LinkRisk session: {exc}") from exc

        events: list[dict[str, Any]] = []
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SessionStoreError(
                    f"Session journal is corrupt at line {line_number}: {exc.msg}"
                ) from exc
            if int(event.get("version", -1)) != SCHEMA_VERSION:
                raise SessionStoreError(
                    f"Unsupported session journal version at line {line_number}"
                )
            if not isinstance(event.get("payload"), dict):
                raise SessionStoreError(
                    f"Session journal payload is invalid at line {line_number}"
                )
            events.append(event)
        return events

    def has_events(self) -> bool:
        return bool(self.events())

    def status(self) -> dict[str, Any]:
        events = self.events()
        return {
            "enabled": True,
            "event_count": len(events),
            "transaction_count": sum(1 for event in events if event.get("type") == "transaction"),
            "journal_exists": self.path.exists(),
        }

    def clear(self) -> None:
        try:
            with self._lock:
                if self.path.exists():
                    self.path.unlink()
        except OSError as exc:
            raise SessionStoreError(f"Could not clear LinkRisk session: {exc}") from exc

    def replay(self, engine: Any, razorpay_state: Any | None = None) -> int:
        """Rebuild engine causal state from the persisted event sequence.

        Transaction decisions are recomputed at their original timestamps using
        the frozen models. This restores both visible records and the historical
        state required by Mentalist's causal windows.
        """
        events = self.events()
        replayed = 0
        for event in events:
            event_type = str(event["type"])
            payload = event["payload"]

            if event_type == "transaction":
                engine.clock = float(payload["transaction_time"])
                live_input = LiveTransactionInput(**payload["input"])
                record = engine.score_event(
                    live_input,
                    transaction_id=str(payload["transaction_id"]),
                )
                integration = payload.get("integration")
                if isinstance(integration, dict):
                    record["integration"] = dict(integration)
                    payment_id = str(integration.get("payment_id") or "").strip()
                    if razorpay_state is not None and payment_id:
                        razorpay_state.bind_payment(payment_id, str(payload["transaction_id"]))
                replayed += 1
                continue

            if event_type == "adjudication":
                engine.clock = float(payload["recorded_at"])
                engine.adjudicate(str(payload["transaction_id"]), str(payload["outcome"]))
                continue

            if event_type == "clear_adjudication":
                engine.clear_adjudication(str(payload["transaction_id"]))
                continue

            if event_type == "clock":
                engine.clock = float(payload["clock"])
                continue

            raise SessionStoreError(f"Unknown session journal event type: {event_type}")

        return replayed
