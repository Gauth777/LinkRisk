"""Durable session journal for the LinkRisk demo runtime.

The live engine remains the source of truth for scoring. A local JSONL journal is
always maintained; when server-side Supabase credentials are configured, the same
causal event sequence is mirrored remotely and can be replayed after a backend
restart. Model/runtime internals are never pickled.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
import os
from pathlib import Path
from threading import Lock
from typing import Any, Mapping

from backend.supabase_store import SupabaseMerchantStore, SupabaseStoreError
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
    """Append-only local journal with optional private Supabase mirroring."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = Lock()
        self.remote = SupabaseMerchantStore()

    def _append_local(self, event_type: str, payload: Mapping[str, Any]) -> None:
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

    def _mirror(self, event_type: str, payload: Mapping[str, Any]) -> None:
        if not self.remote.enabled:
            return
        try:
            self.remote.append_event(event_type, payload)
        except SupabaseStoreError:
            # Remote persistence is additive. A temporary DB outage must not make
            # a scored/verified payment fail or corrupt the local causal journal.
            pass

    def _append(self, event_type: str, payload: Mapping[str, Any]) -> None:
        self._append_local(event_type, payload)
        self._mirror(event_type, payload)

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
        normalized = outcome.strip().lower()
        payload = {
            "transaction_id": transaction_id,
            "outcome": normalized,
            "recorded_at": float(recorded_at),
        }
        self._append("adjudication", payload)
        if self.remote.enabled:
            try:
                self.remote.upsert_adjudication(transaction_id, normalized, float(recorded_at))
            except SupabaseStoreError:
                pass

    def append_clear_adjudication(self, transaction_id: str) -> None:
        self._append("clear_adjudication", {"transaction_id": transaction_id})

    def append_analyst_investigation(self, transaction_id: str, requested_at: float) -> None:
        self._append(
            "analyst_jane",
            {
                "transaction_id": transaction_id,
                "requested_at": float(requested_at),
            },
        )

    def append_clock(self, clock: float) -> None:
        self._append("clock", {"clock": float(clock)})

    def _local_events(self) -> list[dict[str, Any]]:
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

    def events(self) -> list[dict[str, Any]]:
        # Remote history is authoritative when configured because Render/local
        # filesystems may be ephemeral. Fall back to the local journal on any
        # remote outage so the live demo remains available.
        if self.remote.enabled:
            try:
                remote_events = self.remote.events()
                if remote_events:
                    return remote_events
            except SupabaseStoreError:
                pass
        return self._local_events()

    def has_events(self) -> bool:
        return bool(self.events())

    def status(self) -> dict[str, Any]:
        local_events = self._local_events()
        remote_status = self.remote.status()
        try:
            effective_events = self.events()
        except SessionStoreError:
            effective_events = local_events
        return {
            "enabled": True,
            "event_count": len(effective_events),
            "transaction_count": sum(1 for event in effective_events if event.get("type") == "transaction"),
            "journal_exists": self.path.exists(),
            "source": "supabase" if self.remote.enabled and remote_status.get("healthy") else "local",
            "merchant_memory": remote_status,
        }

    def clear(self) -> None:
        """Clear only the disposable local/runtime journal.

        Persistent merchant memory is intentionally not deleted by a public UI
        reset. This prevents a demo visitor from erasing historical risk context.
        """
        try:
            with self._lock:
                if self.path.exists():
                    self.path.unlink()
        except OSError as exc:
            raise SessionStoreError(f"Could not clear LinkRisk session: {exc}") from exc

    def replay(self, engine: Any, razorpay_state: Any | None = None) -> int:
        """Rebuild engine causal state from the persisted event sequence."""
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

            if event_type == "analyst_jane":
                if not hasattr(engine, "deep_investigate"):
                    raise SessionStoreError("Runtime cannot replay analyst Jane investigation")
                engine.deep_investigate(str(payload["transaction_id"]))
                continue

            if event_type == "clock":
                engine.clock = float(payload["clock"])
                continue

            raise SessionStoreError(f"Unknown session journal event type: {event_type}")

        return replayed
