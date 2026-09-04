from __future__ import annotations

from backend.hardening import (
    SlidingWindowLimiter,
    is_serialized_engine_operation,
    rate_limit_policy,
    requires_operator,
)


def test_sensitive_operator_routes_are_classified_without_blocking_public_checkout() -> None:
    assert requires_operator("POST", "/api/transactions/TX-1/deep-investigate")
    assert requires_operator("POST", "/api/transactions/TX-1/jane-escalate")
    assert requires_operator("POST", "/api/transactions/TX-1/adjudicate")
    assert requires_operator("DELETE", "/api/transactions/TX-1/adjudication")
    assert requires_operator("POST", "/api/transactions/TX-1/protect/refund")
    assert requires_operator("POST", "/api/session/advance")
    assert requires_operator("POST", "/api/session/reset")
    assert requires_operator("POST", "/api/transactions")

    assert not requires_operator("POST", "/api/integrations/razorpay/orders")
    assert not requires_operator("POST", "/api/integrations/razorpay/payments/verify")
    assert not requires_operator("GET", "/api/transactions")
    assert not requires_operator("POST", "/api/transactions/TX-1/protection/status")


def test_stateful_scoring_and_feedback_mutations_are_serialized() -> None:
    assert is_serialized_engine_operation("POST", "/api/integrations/razorpay/payments/verify")
    assert is_serialized_engine_operation("POST", "/api/webhooks/razorpay")
    assert is_serialized_engine_operation("POST", "/api/transactions")
    assert is_serialized_engine_operation("POST", "/api/transactions/TX-1/deep-investigate")
    assert is_serialized_engine_operation("POST", "/api/transactions/TX-1/jane-escalate")
    assert is_serialized_engine_operation("POST", "/api/transactions/TX-1/adjudicate")
    assert is_serialized_engine_operation("DELETE", "/api/transactions/TX-1/adjudication")
    assert is_serialized_engine_operation("POST", "/api/session/advance")
    assert is_serialized_engine_operation("POST", "/api/session/reset")

    assert not is_serialized_engine_operation("GET", "/api/transactions")
    assert not is_serialized_engine_operation("POST", "/api/integrations/razorpay/orders")


def test_public_checkout_rate_limit_still_allows_structured_twenty_payment_demo() -> None:
    policy = rate_limit_policy("POST", "/api/integrations/razorpay/orders")
    assert policy == ("razorpay_orders", 30, 60.0)
    assert rate_limit_policy("POST", "/api/transactions/TX-1/jane-escalate") == (
        "jane_operator_escalation",
        20,
        60.0,
    )


def test_sliding_window_limiter_blocks_only_after_limit_and_recovers() -> None:
    limiter = SlidingWindowLimiter()

    allowed, retry = limiter.allow(
        scope="test", client_key="client", limit=2, window_seconds=10.0, now=100.0
    )
    assert allowed and retry == 0

    allowed, retry = limiter.allow(
        scope="test", client_key="client", limit=2, window_seconds=10.0, now=101.0
    )
    assert allowed and retry == 0

    allowed, retry = limiter.allow(
        scope="test", client_key="client", limit=2, window_seconds=10.0, now=102.0
    )
    assert not allowed
    assert retry == 8

    allowed, retry = limiter.allow(
        scope="test", client_key="client", limit=2, window_seconds=10.0, now=111.0
    )
    assert allowed and retry == 0
