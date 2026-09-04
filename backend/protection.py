"""Merchant-protection actions for scored Razorpay Test payments.

This module closes the loop after a LinkRisk REVIEW decision. It does not alter
model scores or routing. A protection action is available only for a scored
Razorpay Test payment whose frozen live decision is REVIEW.

The first supported response is a full normal Razorpay refund. Razorpay's refund
API is called server-side with Test Mode credentials; secrets never reach the
browser. Response state is persisted separately from the causal scoring journal
so operational actions do not become model inputs on replay.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock
import time
from typing import Any, Callable, Mapping

from fastapi import APIRouter, HTTPException
import requests


RAZORPAY_API_BASE = "https://api.razorpay.com/v1"


class ProtectionStoreError(RuntimeError):
    """Raised when merchant-response state cannot be read or persisted."""


class ProtectionStore:
    """Small durable store for demo protection actions, keyed by transaction id."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = Lock()

    def _read_unlocked(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProtectionStoreError(f"Could not read protection state: {exc}") from exc
        if not isinstance(payload, dict):
            raise ProtectionStoreError("Protection state must be a JSON object")
        return {
            str(key): dict(value)
            for key, value in payload.items()
            if isinstance(value, Mapping)
        }

    def get(self, transaction_id: str) -> dict[str, Any] | None:
        with self._lock:
            value = self._read_unlocked().get(transaction_id)
            return dict(value) if value is not None else None

    def put(self, transaction_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            state = self._read_unlocked()
            state[transaction_id] = dict(payload)
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(
                    json.dumps(state, indent=2, sort_keys=True),
                    encoding="utf-8",
                )
            except OSError as exc:
                raise ProtectionStoreError(f"Could not persist protection state: {exc}") from exc
            return dict(state[transaction_id])

    def clear(self) -> None:
        with self._lock:
            try:
                if self.path.exists():
                    self.path.unlink()
            except OSError as exc:
                raise ProtectionStoreError(f"Could not clear protection state: {exc}") from exc

    def summary(self) -> dict[str, Any]:
        with self._lock:
            state = self._read_unlocked()
        accepted = [
            item for item in state.values()
            if str(item.get("refund_status") or "") in {"pending", "processed"}
        ]
        processed = [
            item for item in accepted
            if str(item.get("refund_status") or "") == "processed"
        ]
        return {
            "responses": len(state),
            "refunds_initiated": len(accepted),
            "protected_payments": len(processed),
            "protected_amount": round(
                sum(float(item.get("amount") or 0.0) for item in processed),
                2,
            ),
            "currency": "INR",
        }


def _credentials() -> tuple[str, str]:
    key_id = os.getenv("RAZORPAY_KEY_ID", "").strip()
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
    if not key_id or not key_secret:
        raise HTTPException(status_code=503, detail="Razorpay credentials are not configured.")
    if not key_id.startswith("rzp_test_"):
        raise HTTPException(
            status_code=503,
            detail="Merchant Protection is restricted to Razorpay Test Mode in this buildathon deployment.",
        )
    return key_id, key_secret


def _response_json(response: requests.Response) -> Mapping[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    return payload if isinstance(payload, Mapping) else {}


def _raise_razorpay(response: requests.Response, operation: str) -> None:
    if response.ok:
        return
    payload = _response_json(response)
    error = payload.get("error")
    detail = ""
    if isinstance(error, Mapping):
        detail = str(error.get("description") or error.get("reason") or "").strip()
    raise HTTPException(
        status_code=502,
        detail=f"Razorpay {operation} failed: {detail or f'HTTP {response.status_code}'}",
    )


def create_full_test_refund(
    *,
    key_id: str,
    key_secret: str,
    payment_id: str,
    transaction_id: str,
) -> Mapping[str, Any]:
    """Create a full normal refund for one Razorpay Test payment.

    Omitting ``amount`` intentionally requests a full refund. The operation uses
    normal refund speed and includes only non-sensitive LinkRisk reference notes.
    """
    try:
        response = requests.post(
            f"{RAZORPAY_API_BASE}/payments/{payment_id}/refund",
            auth=(key_id, key_secret),
            json={
                "speed": "normal",
                "notes": {
                    "linkrisk_action": "merchant_protection",
                    "linkrisk_transaction": transaction_id,
                },
            },
            timeout=12,
        )
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Razorpay refund request failed: {type(exc).__name__}",
        ) from exc
    _raise_razorpay(response, "refund")
    payload = _response_json(response)
    refund_id = str(payload.get("id") or "")
    if not refund_id.startswith("rfnd_"):
        raise HTTPException(status_code=502, detail="Razorpay refund returned no valid refund id.")
    if str(payload.get("payment_id") or "") != payment_id:
        raise HTTPException(status_code=502, detail="Razorpay refund payment id mismatch.")
    return payload


def _eligible_record(engine: Any, transaction_id: str) -> tuple[dict[str, Any], str]:
    try:
        record = engine.get_record(transaction_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown transaction: {transaction_id}") from exc

    action = str((record.get("decision") or {}).get("action") or "")
    if action != "REVIEW":
        raise HTTPException(
            status_code=409,
            detail="Merchant Protection refund is available only for a final REVIEW decision.",
        )

    integration = record.get("integration")
    if not isinstance(integration, Mapping):
        raise HTTPException(
            status_code=409,
            detail="This REVIEW case is not backed by a Razorpay payment.",
        )
    payment_id = str(integration.get("payment_id") or "").strip()
    source = str(integration.get("source") or "")
    if not payment_id.startswith("pay_") or not source.startswith("razorpay"):
        raise HTTPException(
            status_code=409,
            detail="This REVIEW case has no eligible Razorpay payment to protect.",
        )
    return record, payment_id


def build_protection_router(
    *,
    engine_provider: Callable[[], Any],
    root: Path,
) -> APIRouter:
    """Build POST-only routes so they remain ahead of no GET-specific concerns."""
    router = APIRouter()
    store = ProtectionStore(root / ".linkrisk" / "protection.json")

    @router.post("/api/transactions/{transaction_id}/protection/status")
    def protection_status(transaction_id: str) -> dict[str, Any]:
        engine = engine_provider()
        existing = store.get(transaction_id)
        if existing is not None:
            return {
                "eligible": True,
                "has_response": True,
                "protection": existing,
            }

        try:
            record, payment_id = _eligible_record(engine, transaction_id)
        except HTTPException as exc:
            if exc.status_code == 409:
                return {
                    "eligible": False,
                    "has_response": False,
                    "reason": exc.detail,
                    "protection": None,
                }
            raise
        return {
            "eligible": True,
            "has_response": False,
            "payment_id": payment_id,
            "amount": float(record["input"].amount),
            "protection": None,
        }

    @router.post("/api/transactions/{transaction_id}/protect/refund")
    def protect_with_refund(transaction_id: str) -> dict[str, Any]:
        engine = engine_provider()
        record, payment_id = _eligible_record(engine, transaction_id)

        existing = store.get(transaction_id)
        if existing is not None and str(existing.get("refund_status") or "") in {"pending", "processed"}:
            return {
                "ok": True,
                "duplicate": True,
                "protection": existing,
            }

        key_id, key_secret = _credentials()
        refund = create_full_test_refund(
            key_id=key_id,
            key_secret=key_secret,
            payment_id=payment_id,
            transaction_id=transaction_id,
        )

        amount_subunits = int(refund.get("amount") or 0)
        protection = {
            "action": "RAZORPAY_TEST_REFUND",
            "provider": "razorpay",
            "test_mode": True,
            "transaction_id": transaction_id,
            "payment_id": payment_id,
            "refund_id": str(refund.get("id") or ""),
            "refund_status": str(refund.get("status") or "pending"),
            "speed_requested": str(refund.get("speed_requested") or "normal"),
            "speed_processed": refund.get("speed_processed"),
            "amount_subunits": amount_subunits,
            "amount": amount_subunits / 100.0,
            "currency": str(refund.get("currency") or "INR"),
            "created_at": int(refund.get("created_at") or time.time()),
            "response_reason": "Final REVIEW decision — merchant protection action",
        }
        stored = store.put(transaction_id, protection)
        record["protection"] = dict(stored)
        return {
            "ok": True,
            "duplicate": False,
            "protection": stored,
        }

    @router.post("/api/protection/summary")
    def protection_summary() -> dict[str, Any]:
        return store.summary()

    @router.post("/api/protection/reset")
    def reset_protection() -> dict[str, Any]:
        store.clear()
        return {"ok": True}

    return router
