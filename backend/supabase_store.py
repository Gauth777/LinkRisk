"""Optional server-side Supabase persistence for LinkRisk merchant memory.

The risk engine remains deterministic and causal. This store persists the event
journal plus a privacy-preserving operational index. Raw email/contact values are
never written to the risk tables; stable HMAC tokens and masked display values are
used instead.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import hashlib
import hmac
import json
import os
from typing import Any, Mapping

import requests

from linkrisk.live_engine import LiveTransactionInput


LABEL_DELAY_SECONDS = 72 * 60 * 60


class SupabaseStoreError(RuntimeError):
    """Raised when configured persistent merchant memory is unavailable."""


def _normalise_contact(value: object) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _normalise_email(value: object) -> str:
    return str(value or "").strip().lower()


def _token(secret: str, namespace: str, value: str) -> str | None:
    value = value.strip().lower()
    if not value:
        return None
    digest = hmac.new(secret.encode("utf-8"), f"{namespace}:{value}".encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{namespace}:{digest[:24]}"


def privacy_safe_identity(payment: Mapping[str, Any], secret: str) -> dict[str, str | None]:
    """Derive stable pseudonymous identity fields without persisting raw PII."""
    contact = _normalise_contact(payment.get("contact"))
    email = _normalise_email(payment.get("email"))
    email_domain = email.rsplit("@", 1)[-1] if "@" in email else None
    contact_masked = f"******{contact[-4:]}" if len(contact) >= 4 else None

    contact_token = _token(secret, "phone", contact)
    email_token = _token(secret, "email", email)
    stable_parts = [part for part in (contact_token, email_token) if part]
    customer_material = "|".join(stable_parts) or str(payment.get("id") or "unknown")
    customer_token = _token(secret, "customer", customer_material)

    return {
        "customer_token": customer_token,
        "contact_token": contact_token,
        "contact_masked": contact_masked,
        "email_token": email_token,
        "email_domain": email_domain,
    }


class SupabaseMerchantStore:
    """Backend-only persistence using Supabase's REST Data API.

    Requires SUPABASE_URL plus SUPABASE_SECRET_KEY (or SUPABASE_SERVICE_ROLE_KEY).
    Secret/service credentials must never be exposed to the React bundle.
    """

    def __init__(self) -> None:
        self.url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
        self.key = (
            os.getenv("SUPABASE_SECRET_KEY", "").strip()
            or os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
        )
        self.identity_secret = (
            os.getenv("LINKRISK_IDENTITY_SECRET", "").strip()
            or os.getenv("RAZORPAY_KEY_SECRET", "").strip()
        )

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.key and self.identity_secret)

    def _headers(self, *, prefer: str | None = None) -> dict[str, str]:
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }
        if prefer:
            headers["Prefer"] = prefer
        return headers

    def _request(self, method: str, table: str, *, params: dict[str, str] | None = None, payload: Any = None, prefer: str | None = None) -> Any:
        if not self.enabled:
            raise SupabaseStoreError("Supabase merchant memory is not configured")
        try:
            response = requests.request(
                method,
                f"{self.url}/rest/v1/{table}",
                params=params,
                json=payload,
                headers=self._headers(prefer=prefer),
                timeout=8,
            )
        except requests.RequestException as exc:
            raise SupabaseStoreError(f"Supabase request failed: {type(exc).__name__}") from exc
        if not response.ok:
            detail = response.text[:500].strip()
            raise SupabaseStoreError(f"Supabase {table} returned HTTP {response.status_code}: {detail}")
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return None

    @staticmethod
    def _event_key(event_type: str, payload: Mapping[str, Any]) -> str:
        canonical = json.dumps({"type": event_type, "payload": dict(payload)}, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def append_event(self, event_type: str, payload: Mapping[str, Any]) -> None:
        if not self.enabled:
            return
        transaction_id = str(payload.get("transaction_id") or "") or None
        event_time = payload.get("transaction_time", payload.get("recorded_at", payload.get("clock")))
        row = {
            "event_key": self._event_key(event_type, payload),
            "event_type": event_type,
            "transaction_id": transaction_id,
            "event_time": float(event_time) if event_time is not None else None,
            "payload": dict(payload),
        }
        self._request("POST", "linkrisk_session_events", payload=row, prefer="resolution=ignore-duplicates,return=minimal")

    def events(self) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        rows = self._request(
            "GET",
            "linkrisk_session_events",
            params={"select": "event_type,payload", "order": "id.asc"},
        ) or []
        return [{"version": 1, "type": row["event_type"], "payload": row["payload"]} for row in rows]

    def upsert_payment(self, record: Mapping[str, Any], payment: Mapping[str, Any]) -> None:
        if not self.enabled:
            return
        decision = record.get("decision") if isinstance(record.get("decision"), Mapping) else {}
        mentalist = record.get("mentalist") if isinstance(record.get("mentalist"), Mapping) else {}
        analyst = record.get("analyst_jane") if isinstance(record.get("analyst_jane"), Mapping) else {}
        case_file = record.get("case_file") if isinstance(record.get("case_file"), Mapping) else {}
        integration = record.get("integration") if isinstance(record.get("integration"), Mapping) else {}
        event = record.get("input")
        if is_dataclass(event):
            event = asdict(event)
        event = event if isinstance(event, Mapping) else {}
        identity = privacy_safe_identity(payment, self.identity_secret)

        try:
            amount = float(payment.get("amount") or 0) / 100.0
        except (TypeError, ValueError):
            amount = float(event.get("amount") or 0)

        row = {
            "transaction_id": str(record["transaction_id"]),
            "razorpay_payment_id": str(payment.get("id") or "") or None,
            "razorpay_order_id": str(payment.get("order_id") or "") or None,
            "amount": amount,
            "currency": str(payment.get("currency") or integration.get("currency") or "") or None,
            "payment_method": str(payment.get("method") or integration.get("payment_method") or "") or None,
            "payment_status": str(payment.get("status") or integration.get("payment_status") or "") or None,
            **identity,
            "device_info": str(event.get("device_info") or "") or None,
            "browser_context": str(event.get("browser_context") or "") or None,
            "device_type": str(event.get("device_type") or "") or None,
            "baseline_risk": decision.get("baseline_risk"),
            "linkrisk_risk": decision.get("linkrisk_risk"),
            "graph_confidence": decision.get("graph_confidence"),
            "jane_score": analyst.get("score", mentalist.get("score")),
            "jane_clue_count": analyst.get("clue_count", mentalist.get("clue_count")),
            "v5_action": decision.get("v5_action"),
            "final_action": decision.get("action"),
            "routing_reason": decision.get("routing_reason"),
            "policy_version": decision.get("policy_version"),
            "trusted_history_channels": int(case_file.get("trusted_history_channels") or 0),
            "trusted_fraud_channels": int(case_file.get("trusted_fraud_channels") or 0),
            "transaction_time": float(record["transaction_time"]),
            "source": integration.get("source"),
        }
        self._request("POST", "linkrisk_payment_intelligence", payload=row, prefer="resolution=merge-duplicates,return=minimal")

    def upsert_adjudication(self, transaction_id: str, outcome: str, recorded_at: float) -> None:
        if not self.enabled:
            return
        row = {
            "transaction_id": transaction_id,
            "outcome": outcome.strip().lower(),
            "recorded_at": float(recorded_at),
            "trusted_after": float(recorded_at) + LABEL_DELAY_SECONDS,
        }
        self._request("POST", "linkrisk_adjudications", payload=row, prefer="resolution=merge-duplicates,return=minimal")

    def status(self) -> dict[str, Any]:
        if not self.enabled:
            return {"enabled": False, "healthy": False, "reason": "server credentials not configured"}
        try:
            rows = self._request("GET", "linkrisk_payment_intelligence", params={"select": "transaction_id", "limit": "1"}) or []
            return {"enabled": True, "healthy": True, "reachable": True, "sample_rows": len(rows)}
        except SupabaseStoreError as exc:
            return {"enabled": True, "healthy": False, "error": str(exc)}
