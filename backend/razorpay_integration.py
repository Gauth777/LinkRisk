"""Razorpay Test/Live webhook ingestion helpers for LinkRisk.

The integration deliberately separates Razorpay payment fields from merchant-side
telemetry. Razorpay does not provide payer browser/device telemetry in the
standard Payment entity, so absent telemetry is represented by payment-unique
unknown contexts rather than invented shared identities.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import hmac
from threading import Lock
from typing import Any, Mapping

from linkrisk.live_engine import LiveTransactionInput


SUPPORTED_PAYMENT_EVENTS = frozenset({"payment.authorized", "payment.captured"})


@dataclass(frozen=True)
class MerchantTelemetry:
    """Merchant-observed context registered before/around checkout.

    ``reference_id`` should normally be the Razorpay order id. It may also be a
    payment id if telemetry becomes available only after checkout.
    """

    reference_id: str
    payment_profile: str
    device_info: str
    browser_context: str
    receiver_domain: str = "merchant.local"
    device_type: str = "unknown"


class RazorpayIntegrationState:
    """Small in-memory idempotency + telemetry store for the demo runtime."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._telemetry: dict[str, MerchantTelemetry] = {}
        self._claimed_events: set[str] = set()
        self._processed_events: set[str] = set()
        self._payment_to_transaction: dict[str, str] = {}

    def reset(self) -> None:
        with self._lock:
            self._telemetry.clear()
            self._claimed_events.clear()
            self._processed_events.clear()
            self._payment_to_transaction.clear()

    def register_telemetry(self, telemetry: MerchantTelemetry) -> None:
        with self._lock:
            self._telemetry[telemetry.reference_id] = telemetry

    def telemetry_for_payment(self, payment: Mapping[str, Any]) -> MerchantTelemetry | None:
        payment_id = str(payment.get("id") or "")
        order_id = str(payment.get("order_id") or "")
        with self._lock:
            if payment_id and payment_id in self._telemetry:
                return self._telemetry[payment_id]
            if order_id and order_id in self._telemetry:
                return self._telemetry[order_id]
        return None

    def claim_event(self, event_id: str) -> bool:
        """Atomically claim an event. False means duplicate/in-flight."""
        with self._lock:
            if event_id in self._processed_events or event_id in self._claimed_events:
                return False
            self._claimed_events.add(event_id)
            return True

    def complete_event(self, event_id: str) -> None:
        with self._lock:
            self._claimed_events.discard(event_id)
            self._processed_events.add(event_id)

    def release_event(self, event_id: str) -> None:
        with self._lock:
            self._claimed_events.discard(event_id)

    def transaction_for_payment(self, payment_id: str) -> str | None:
        with self._lock:
            return self._payment_to_transaction.get(payment_id)

    def bind_payment(self, payment_id: str, transaction_id: str) -> None:
        with self._lock:
            self._payment_to_transaction[payment_id] = transaction_id

    def status(self) -> dict[str, int]:
        with self._lock:
            return {
                "telemetry_records": len(self._telemetry),
                "processed_events": len(self._processed_events),
                "payments_scored": len(self._payment_to_transaction),
            }


def verify_webhook_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    """Verify Razorpay's HMAC-SHA256 signature over the exact raw body."""
    if not signature or not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


def fallback_event_id(raw_body: bytes) -> str:
    """Deterministic fallback when x-razorpay-event-id is unexpectedly absent."""
    return "body-sha256:" + hashlib.sha256(raw_body).hexdigest()


def payment_entity_from_webhook(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    payment = payload.get("payload", {}).get("payment", {}).get("entity")
    if not isinstance(payment, Mapping):
        raise ValueError("Razorpay webhook does not contain payload.payment.entity")
    payment_id = str(payment.get("id") or "").strip()
    if not payment_id:
        raise ValueError("Razorpay payment entity is missing id")
    return payment


def _email_domain(value: Any) -> str:
    email = str(value or "").strip().lower()
    if "@" not in email:
        return "unknown.local"
    domain = email.rsplit("@", 1)[-1].strip()
    return domain or "unknown.local"


def _pseudonymous_profile(payment: Mapping[str, Any]) -> str:
    """Create a stable non-raw profile token when merchant profile id is absent."""
    material = "|".join(
        str(payment.get(key) or "")
        for key in ("email", "contact", "order_id")
    )
    if not material.replace("|", ""):
        material = str(payment.get("id") or "unknown")
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"rzp-profile-{digest}"


def _card_fields(payment: Mapping[str, Any]) -> tuple[str, str]:
    card = payment.get("card")
    if isinstance(card, Mapping):
        network = str(card.get("network") or payment.get("method") or "unknown").lower()
        card_type = str(card.get("type") or "unknown").lower()
        return network, card_type
    method = str(payment.get("method") or "unknown").lower()
    return method, "unknown"


def normalize_payment_to_live_input(
    payment: Mapping[str, Any],
    telemetry: MerchantTelemetry | None,
) -> LiveTransactionInput:
    """Map a Razorpay Payment entity + optional merchant telemetry into LinkRisk.

    Amount is converted from Razorpay currency subunits to major units. The
    current trained feature adapter remains IEEE-CIS-specific; this function is
    therefore an integration adapter, not a claim that Razorpay fields have the
    same semantics as the masked training columns.
    """
    payment_id = str(payment.get("id") or "").strip()
    if not payment_id:
        raise ValueError("payment id is required")

    try:
        amount = float(payment.get("amount", 0)) / 100.0
    except (TypeError, ValueError) as exc:
        raise ValueError("payment amount must be numeric") from exc
    if amount < 0:
        raise ValueError("payment amount cannot be negative")

    network, card_type = _card_fields(payment)

    if telemetry is None:
        # Do not collapse missing telemetry into one shared context: doing so
        # could create synthetic coordination/reuse evidence.
        payment_profile = _pseudonymous_profile(payment)
        device_info = f"unknown-device:{payment_id}"
        browser_context = f"unknown-browser:{payment_id}"
        receiver_domain = "merchant.local"
        device_type = "unknown"
    else:
        payment_profile = telemetry.payment_profile
        device_info = telemetry.device_info
        browser_context = telemetry.browser_context
        receiver_domain = telemetry.receiver_domain
        device_type = telemetry.device_type

    return LiveTransactionInput(
        amount=amount,
        payment_profile=payment_profile,
        device_info=device_info,
        receiver_domain=receiver_domain,
        browser_context=browser_context,
        product_code="W",
        payer_domain=_email_domain(payment.get("email")),
        device_type=device_type,
        card_network=network,
        card_type=card_type,
    )


def integration_metadata(
    *,
    event_type: str,
    event_id: str,
    payment: Mapping[str, Any],
    telemetry: MerchantTelemetry | None,
) -> dict[str, Any]:
    return {
        "source": "razorpay_webhook",
        "event_type": event_type,
        "event_id": event_id,
        "payment_id": str(payment.get("id") or ""),
        "order_id": payment.get("order_id"),
        "payment_status": payment.get("status"),
        "payment_method": payment.get("method"),
        "currency": payment.get("currency"),
        "created_at": payment.get("created_at"),
        "merchant_telemetry_attached": telemetry is not None,
        "merchant_telemetry": asdict(telemetry) if telemetry is not None else None,
        "raw_payer_ip_used": False,
    }
