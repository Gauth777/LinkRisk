"""Razorpay Test/Live integration helpers for LinkRisk.

The integration deliberately separates Razorpay payment fields from merchant-side
telemetry. Razorpay does not provide payer browser/device telemetry in the
standard Payment entity, so absent telemetry is represented by payment-unique
unknown contexts rather than invented shared identities.

Customer recurrence is derived server-side from the authoritative Razorpay
Payment entity. Client-supplied ``payment_profile`` values are never trusted as
payer identity for scoring.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import hmac
import os
from threading import Lock
from typing import Any, Mapping

import requests

from backend.supabase_store import privacy_safe_identity
from linkrisk.live_engine import LiveTransactionInput


RAZORPAY_API_BASE = "https://api.razorpay.com/v1"
SUPPORTED_PAYMENT_EVENTS = frozenset({"payment.authorized", "payment.captured"})


class RazorpayAPIError(RuntimeError):
    """Sanitised Razorpay API failure safe to surface to the demo UI."""


@dataclass(frozen=True)
class MerchantTelemetry:
    """Merchant-observed context registered before/around checkout.

    ``reference_id`` should normally be the Razorpay order id. It may also be a
    payment id if telemetry becomes available only after checkout.

    ``payment_profile`` is retained only for backward compatibility with older
    demo/session payloads. It is not trusted as customer identity by the Razorpay
    scoring adapter; authoritative Payment contact/email are pseudonymised
    server-side instead.
    """

    reference_id: str
    payment_profile: str
    device_info: str
    browser_context: str
    receiver_domain: str = "merchant.local"
    device_type: str = "unknown"
    product_code: str = "W"


@dataclass(frozen=True)
class CheckoutOrder:
    order_id: str
    amount_subunits: int
    currency: str


class RazorpayIntegrationState:
    """Small in-memory checkout/idempotency/telemetry store for the demo runtime."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._telemetry: dict[str, MerchantTelemetry] = {}
        self._checkout_orders: dict[str, CheckoutOrder] = {}
        self._claimed_events: set[str] = set()
        self._processed_events: set[str] = set()
        self._payment_to_transaction: dict[str, str] = {}

    def reset(self) -> None:
        with self._lock:
            self._telemetry.clear()
            self._checkout_orders.clear()
            self._claimed_events.clear()
            self._processed_events.clear()
            self._payment_to_transaction.clear()

    def register_telemetry(self, telemetry: MerchantTelemetry) -> None:
        with self._lock:
            self._telemetry[telemetry.reference_id] = telemetry

    def register_checkout_order(self, order: CheckoutOrder) -> None:
        with self._lock:
            self._checkout_orders[order.order_id] = order

    def checkout_order(self, order_id: str) -> CheckoutOrder | None:
        with self._lock:
            return self._checkout_orders.get(order_id)

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
                "checkout_orders": len(self._checkout_orders),
                "telemetry_records": len(self._telemetry),
                "processed_events": len(self._processed_events),
                "payments_scored": len(self._payment_to_transaction),
            }


def _response_json(response: requests.Response) -> Mapping[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    return payload if isinstance(payload, Mapping) else {}


def _raise_for_razorpay(response: requests.Response, operation: str) -> None:
    if response.ok:
        return
    payload = _response_json(response)
    error = payload.get("error")
    if isinstance(error, Mapping):
        detail = str(error.get("description") or error.get("reason") or "")
    else:
        detail = ""
    message = detail.strip() or f"HTTP {response.status_code}"
    raise RazorpayAPIError(f"Razorpay {operation} failed: {message}")


def create_razorpay_order(
    *,
    key_id: str,
    key_secret: str,
    amount_subunits: int,
    currency: str,
    receipt: str,
) -> Mapping[str, Any]:
    """Create an immutable Razorpay Order server-side."""
    try:
        response = requests.post(
            f"{RAZORPAY_API_BASE}/orders",
            auth=(key_id, key_secret),
            json={
                "amount": int(amount_subunits),
                "currency": currency,
                "receipt": receipt,
            },
            timeout=10,
        )
    except requests.RequestException as exc:
        raise RazorpayAPIError(f"Razorpay order request failed: {type(exc).__name__}") from exc
    _raise_for_razorpay(response, "order creation")
    payload = _response_json(response)
    if not str(payload.get("id") or "").startswith("order_"):
        raise RazorpayAPIError("Razorpay order creation returned no valid order id")
    return payload


def fetch_razorpay_payment(*, key_id: str, key_secret: str, payment_id: str) -> Mapping[str, Any]:
    """Fetch the authoritative Payment entity after Checkout callback verification."""
    try:
        response = requests.get(
            f"{RAZORPAY_API_BASE}/payments/{payment_id}",
            auth=(key_id, key_secret),
            timeout=10,
        )
    except requests.RequestException as exc:
        raise RazorpayAPIError(f"Razorpay payment lookup failed: {type(exc).__name__}") from exc
    _raise_for_razorpay(response, "payment lookup")
    payload = _response_json(response)
    if str(payload.get("id") or "") != payment_id:
        raise RazorpayAPIError("Razorpay payment lookup returned an unexpected payment id")
    return payload


def verify_webhook_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    """Verify Razorpay's HMAC-SHA256 signature over the exact raw body."""
    if not signature or not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


def verify_payment_signature(order_id: str, payment_id: str, signature: str, key_secret: str) -> bool:
    """Verify Standard Checkout success signature using the server-known order id."""
    if not order_id or not payment_id or not signature or not key_secret:
        return False
    signed = f"{order_id}|{payment_id}".encode("utf-8")
    expected = hmac.new(key_secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
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
    """Create a non-raw fallback profile when no server identity key is available."""
    material = "|".join(
        str(payment.get(key) or "")
        for key in ("email", "contact", "order_id")
    )
    if not material.replace("|", ""):
        material = str(payment.get("id") or "unknown")
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"rzp-profile-{digest}"


def _server_identity_secret(explicit: str | None = None) -> str:
    """Resolve the server-only key used to pseudonymise authoritative payer identity."""
    if explicit and explicit.strip():
        return explicit.strip()
    return (
        os.getenv("LINKRISK_IDENTITY_SECRET", "").strip()
        or os.getenv("RAZORPAY_KEY_SECRET", "").strip()
        or os.getenv("RAZORPAY_WEBHOOK_SECRET", "").strip()
    )


def _risk_profile_from_payment(payment: Mapping[str, Any], identity_secret: str | None = None) -> str:
    """Return a stable privacy-safe recurring profile for risk features.

    Priority is deliberately phone -> email -> payment-specific customer token.
    This keeps a verified phone stable even if a payer changes email while raw
    PII never enters the feature adapter.
    """
    secret = _server_identity_secret(identity_secret)
    if secret:
        identity = privacy_safe_identity(payment, secret)
        for key in ("contact_token", "email_token", "customer_token"):
            token = identity.get(key)
            if token:
                return str(token)
    return _pseudonymous_profile(payment)


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
    *,
    identity_secret: str | None = None,
) -> LiveTransactionInput:
    """Map a Razorpay Payment entity + optional merchant telemetry into LinkRisk.

    Amount is converted from Razorpay currency subunits to major units. Customer
    recurrence is derived from authoritative Razorpay contact/email and converted
    to an HMAC token before entering the model. ``telemetry.payment_profile`` is
    intentionally ignored. Merchant telemetry may still contribute device,
    browser, receiver and product context.

    The current trained feature adapter remains IEEE-CIS-specific; this function
    is therefore an integration adapter, not a claim that Razorpay fields have
    the same semantics as the masked training columns.
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
    payment_profile = _risk_profile_from_payment(payment, identity_secret)

    if telemetry is None:
        # Do not collapse missing telemetry into one shared context: doing so
        # could create synthetic coordination/reuse evidence.
        device_info = f"unknown-device:{payment_id}"
        browser_context = f"unknown-browser:{payment_id}"
        receiver_domain = "merchant.local"
        device_type = "unknown"
        product_code = "W"
    else:
        device_info = telemetry.device_info
        browser_context = telemetry.browser_context
        receiver_domain = telemetry.receiver_domain
        device_type = telemetry.device_type
        product_code = telemetry.product_code

    return LiveTransactionInput(
        amount=amount,
        payment_profile=payment_profile,
        device_info=device_info,
        receiver_domain=receiver_domain,
        browser_context=browser_context,
        product_code=product_code,
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
    source: str = "razorpay_webhook",
) -> dict[str, Any]:
    telemetry_payload = asdict(telemetry) if telemetry is not None else None
    if telemetry_payload is not None:
        # Legacy client profile names are not authoritative payer identity and
        # should not be copied into new durable integration events.
        telemetry_payload.pop("payment_profile", None)

    return {
        "source": source,
        "event_type": event_type,
        "event_id": event_id,
        "payment_id": str(payment.get("id") or ""),
        "order_id": payment.get("order_id"),
        "payment_status": payment.get("status"),
        "payment_method": payment.get("method"),
        "currency": payment.get("currency"),
        "created_at": payment.get("created_at"),
        "merchant_telemetry_attached": telemetry is not None,
        "merchant_telemetry": telemetry_payload,
        "risk_identity": "server_pseudonymous_authoritative_payment",
        "raw_payer_ip_used": False,
    }
