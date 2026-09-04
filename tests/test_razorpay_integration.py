from __future__ import annotations

import hashlib
import hmac

from backend.razorpay_integration import (
    CheckoutOrder,
    MerchantTelemetry,
    RazorpayIntegrationState,
    fallback_event_id,
    normalize_payment_to_live_input,
    payment_entity_from_webhook,
    verify_payment_signature,
    verify_webhook_signature,
)
from backend.supabase_store import privacy_safe_identity


def _payment(payment_id: str = "pay_demo", order_id: str = "order_demo") -> dict:
    return {
        "id": payment_id,
        "amount": 125000,
        "currency": "INR",
        "status": "captured",
        "order_id": order_id,
        "method": "card",
        "email": "buyer@example.com",
        "contact": "+919999999999",
        "card": {"network": "Visa", "type": "debit"},
    }


def test_webhook_signature_uses_exact_raw_body() -> None:
    raw = b'{"event":"payment.captured","payload":{"x":1}}'
    secret = "buildathon-secret"
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()

    assert verify_webhook_signature(raw, signature, secret)
    assert not verify_webhook_signature(raw + b" ", signature, secret)
    assert not verify_webhook_signature(raw, "bad-signature", secret)


def test_checkout_payment_signature_uses_server_order_id() -> None:
    order_id = "order_demo"
    payment_id = "pay_demo"
    secret = "test-key-secret"
    signature = hmac.new(
        secret.encode(),
        f"{order_id}|{payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()

    assert verify_payment_signature(order_id, payment_id, signature, secret)
    assert not verify_payment_signature("order_other", payment_id, signature, secret)
    assert not verify_payment_signature(order_id, "pay_other", signature, secret)


def test_missing_event_id_fallback_is_deterministic() -> None:
    raw = b'{"event":"payment.captured"}'
    assert fallback_event_id(raw) == fallback_event_id(raw)
    assert fallback_event_id(raw).startswith("body-sha256:")


def test_payment_entity_parser_requires_payment_entity() -> None:
    payment = _payment()
    payload = {"event": "payment.captured", "payload": {"payment": {"entity": payment}}}
    assert payment_entity_from_webhook(payload)["id"] == "pay_demo"


def test_missing_merchant_telemetry_does_not_create_shared_device_context() -> None:
    first = normalize_payment_to_live_input(_payment("pay_a", "order_a"), None)
    second = normalize_payment_to_live_input(_payment("pay_b", "order_b"), None)

    assert first.amount == 1250.0
    assert first.device_info != second.device_info
    assert first.browser_context != second.browser_context
    assert first.device_info.startswith("unknown-device:")
    assert first.card_network == "visa"
    assert first.card_type == "debit"
    assert first.payer_domain == "example.com"


def test_registered_order_telemetry_enriches_payment() -> None:
    state = RazorpayIntegrationState()
    telemetry = MerchantTelemetry(
        reference_id="order_demo",
        payment_profile="CUSTOMER-42",
        device_info="Chrome / Windows",
        browser_context="session-device-42",
        receiver_domain="merchant.example",
        device_type="desktop",
        product_code="R",
    )
    state.register_telemetry(telemetry)

    payment = _payment()
    matched = state.telemetry_for_payment(payment)
    event = normalize_payment_to_live_input(payment, matched)

    assert matched == telemetry
    assert event.payment_profile == "CUSTOMER-42"
    assert event.device_info == "Chrome / Windows"
    assert event.browser_context == "session-device-42"
    assert event.receiver_domain == "merchant.example"
    assert event.product_code == "R"


def test_checkout_order_and_idempotency_state() -> None:
    state = RazorpayIntegrationState()
    order = CheckoutOrder(order_id="order_demo", amount_subunits=125000, currency="INR")
    state.register_checkout_order(order)

    assert state.checkout_order("order_demo") == order
    assert state.checkout_order("order_missing") is None

    assert state.claim_event("evt_1")
    assert not state.claim_event("evt_1")
    state.complete_event("evt_1")
    assert not state.claim_event("evt_1")

    state.bind_payment("pay_demo", "RZP-pay_demo")
    assert state.transaction_for_payment("pay_demo") == "RZP-pay_demo"

    status = state.status()
    assert status["checkout_orders"] == 1
    assert status["processed_events"] == 1
    assert status["payments_scored"] == 1


def test_privacy_safe_identity_is_stable_and_does_not_return_raw_pii() -> None:
    payment = _payment()
    first = privacy_safe_identity(payment, "merchant-secret")
    second = privacy_safe_identity(payment, "merchant-secret")

    assert first == second
    assert first["contact_masked"] == "******9999"
    assert first["email_domain"] == "example.com"
    assert str(first["contact_token"]).startswith("phone:")
    assert str(first["email_token"]).startswith("email:")
    assert str(first["customer_token"]).startswith("customer:")

    encoded = repr(first)
    assert "+919999999999" not in encoded
    assert "buyer@example.com" not in encoded


def test_privacy_safe_identity_changes_with_identity_or_secret() -> None:
    base = privacy_safe_identity(_payment(), "merchant-secret")
    other_payment = _payment()
    other_payment["contact"] = "+918888888888"
    changed_identity = privacy_safe_identity(other_payment, "merchant-secret")
    changed_secret = privacy_safe_identity(_payment(), "other-secret")

    assert base["customer_token"] != changed_identity["customer_token"]
    assert base["customer_token"] != changed_secret["customer_token"]
