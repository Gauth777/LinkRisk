"""Server-side Razorpay Standard Checkout flow for the LinkRisk demo."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import os
import secrets
import time
from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.razorpay_integration import (
    CheckoutOrder,
    MerchantTelemetry,
    RazorpayAPIError,
    RazorpayIntegrationState,
    create_razorpay_order,
    fetch_razorpay_payment,
    integration_metadata,
    normalize_payment_to_live_input,
    verify_payment_signature,
)
from linkrisk.live_engine import LiveLinkRiskEngine


class CheckoutOrderRequest(BaseModel):
    amount: float = Field(gt=0, le=10_000_000)
    payment_profile: str = Field(min_length=1, max_length=120)
    device_info: str = Field(min_length=1, max_length=160)
    browser_context: str = Field(min_length=1, max_length=160)
    receiver_domain: str = Field(default="merchant.local", min_length=1, max_length=160)
    device_type: str = Field(default="desktop", min_length=1, max_length=40)
    product_code: str = Field(default="W", min_length=1, max_length=12)
    customer_name: str = Field(default="Demo Customer", min_length=1, max_length=120)
    customer_email: str = Field(default="demo@example.com", min_length=3, max_length=160)
    customer_contact: str = Field(default="+919999999999", min_length=5, max_length=24)


class CheckoutVerificationRequest(BaseModel):
    razorpay_payment_id: str = Field(min_length=1, max_length=160)
    razorpay_order_id: str = Field(min_length=1, max_length=160)
    razorpay_signature: str = Field(min_length=1, max_length=256)


def _test_credentials() -> tuple[str, str]:
    key_id = os.getenv("RAZORPAY_KEY_ID", "").strip()
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
    if not key_id or not key_secret:
        raise HTTPException(
            status_code=503,
            detail="RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET are not configured.",
        )
    if not key_id.startswith("rzp_test_"):
        raise HTTPException(
            status_code=503,
            detail="LinkRisk buildathon checkout accepts Razorpay Test Mode keys only.",
        )
    return key_id, key_secret


def _major_to_subunits(amount: float) -> int:
    major = Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    subunits = int(major * 100)
    if subunits <= 0:
        raise HTTPException(status_code=400, detail="Payment amount must be at least one currency subunit.")
    return subunits


def build_checkout_router(
    *,
    state: RazorpayIntegrationState,
    engine_provider: Callable[[], LiveLinkRiskEngine],
    jsonable: Callable[[Any], Any],
    persist_transaction: Callable[[dict[str, Any]], None] | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/integrations/razorpay/checkout/status")
    def checkout_status() -> dict[str, Any]:
        key_id = os.getenv("RAZORPAY_KEY_ID", "").strip()
        key_secret = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
        return {
            "configured": bool(key_id and key_secret),
            "test_mode": key_id.startswith("rzp_test_"),
            "key_id": key_id if key_id.startswith("rzp_test_") else None,
            "secret_exposed": False,
        }

    @router.post("/api/integrations/razorpay/orders", status_code=201)
    def create_checkout_order(request: CheckoutOrderRequest) -> dict[str, Any]:
        key_id, key_secret = _test_credentials()
        amount_subunits = _major_to_subunits(request.amount)
        currency = "INR"
        receipt = f"lr_{int(time.time() * 1000)}_{secrets.token_hex(3)}"

        try:
            order = create_razorpay_order(
                key_id=key_id,
                key_secret=key_secret,
                amount_subunits=amount_subunits,
                currency=currency,
                receipt=receipt,
            )
        except RazorpayAPIError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        order_id = str(order["id"])
        state.register_checkout_order(
            CheckoutOrder(
                order_id=order_id,
                amount_subunits=amount_subunits,
                currency=currency,
            )
        )
        state.register_telemetry(
            MerchantTelemetry(
                reference_id=order_id,
                payment_profile=request.payment_profile,
                device_info=request.device_info,
                browser_context=request.browser_context,
                receiver_domain=request.receiver_domain,
                device_type=request.device_type,
                product_code=request.product_code,
            )
        )

        return {
            "key_id": key_id,
            "order_id": order_id,
            "amount": amount_subunits,
            "currency": currency,
            "name": "LinkRisk",
            "description": "AI Risk Manager · Test Mode payment",
            "prefill": {
                "name": request.customer_name,
                "email": request.customer_email,
                "contact": request.customer_contact,
            },
            "test_mode": True,
        }

    @router.post("/api/integrations/razorpay/payments/verify")
    def verify_checkout_payment(request: CheckoutVerificationRequest) -> dict[str, Any]:
        key_id, key_secret = _test_credentials()
        expected_order = state.checkout_order(request.razorpay_order_id)
        if expected_order is None:
            raise HTTPException(status_code=400, detail="Unknown Razorpay order. Create the order through LinkRisk first.")

        if not verify_payment_signature(
            expected_order.order_id,
            request.razorpay_payment_id,
            request.razorpay_signature,
            key_secret,
        ):
            raise HTTPException(status_code=401, detail="Invalid Razorpay payment signature.")

        existing_transaction_id = state.transaction_for_payment(request.razorpay_payment_id)
        if existing_transaction_id is not None:
            engine = engine_provider()
            return {
                "verified": True,
                "duplicate_payment": True,
                "transaction": jsonable(engine.get_record(existing_transaction_id)),
            }

        try:
            payment = fetch_razorpay_payment(
                key_id=key_id,
                key_secret=key_secret,
                payment_id=request.razorpay_payment_id,
            )
        except RazorpayAPIError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        if str(payment.get("order_id") or "") != expected_order.order_id:
            raise HTTPException(status_code=409, detail="Razorpay payment order does not match the server-created order.")
        if int(payment.get("amount") or 0) != expected_order.amount_subunits:
            raise HTTPException(status_code=409, detail="Razorpay payment amount does not match the server-created order.")
        if str(payment.get("currency") or "").upper() != expected_order.currency:
            raise HTTPException(status_code=409, detail="Razorpay payment currency does not match the server-created order.")
        if str(payment.get("status") or "") not in {"authorized", "captured"}:
            raise HTTPException(status_code=409, detail="Razorpay payment is not authorized or captured.")

        telemetry = state.telemetry_for_payment(payment)
        try:
            live_input = normalize_payment_to_live_input(payment, telemetry)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        engine = engine_provider()
        engine.clock = max(float(engine.clock), time.time())
        transaction_id = f"RZP-{request.razorpay_payment_id}"
        record = engine.score_event(live_input, transaction_id=transaction_id)
        record["integration"] = integration_metadata(
            source="razorpay_checkout_verify",
            event_type="checkout.verified",
            event_id=f"checkout:{request.razorpay_payment_id}",
            payment=payment,
            telemetry=telemetry,
        )
        if persist_transaction is not None:
            persist_transaction(record)
        state.bind_payment(request.razorpay_payment_id, transaction_id)

        return {
            "verified": True,
            "duplicate_payment": False,
            "transaction": jsonable(record),
        }

    return router