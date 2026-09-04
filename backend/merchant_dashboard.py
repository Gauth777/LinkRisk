"""Read-only dashboard surface for persistent LinkRisk merchant memory.

This router never exposes Supabase credentials or raw identity tokens. It returns
only sanitized operational payment fields that are safe to render in the product
UI. Supabase remains backend-only behind RLS/service credentials.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.supabase_store import SupabaseMerchantStore, SupabaseStoreError


SAFE_PAYMENT_COLUMNS = ",".join(
    [
        "transaction_id",
        "razorpay_payment_id",
        "amount",
        "currency",
        "payment_method",
        "payment_status",
        "contact_masked",
        "email_domain",
        "device_info",
        "device_type",
        "baseline_risk",
        "linkrisk_risk",
        "graph_confidence",
        "jane_score",
        "jane_clue_count",
        "v5_action",
        "final_action",
        "routing_reason",
        "trusted_history_channels",
        "trusted_fraud_channels",
        "transaction_time",
        "source",
        "created_at",
    ]
)


def build_merchant_dashboard_router() -> APIRouter:
    router = APIRouter()
    store = SupabaseMerchantStore()

    @router.get("/api/merchant-memory/transactions")
    def recent_transactions(limit: int = 12) -> dict[str, Any]:
        """Return the newest persistent payments without exposing PII/token keys."""
        bounded_limit = max(1, min(int(limit), 50))
        if not store.enabled:
            return {
                "items": [],
                "persistent": False,
                "healthy": False,
                "reason": "Merchant memory is not configured on the server.",
            }

        try:
            rows = store._request(  # internal backend call; never reachable from browser directly
                "GET",
                "linkrisk_payment_intelligence",
                params={
                    "select": SAFE_PAYMENT_COLUMNS,
                    "order": "transaction_time.desc",
                    "limit": str(bounded_limit),
                },
            ) or []
            return {
                "items": rows,
                "persistent": True,
                "healthy": True,
                "poll_after_ms": 6000,
            }
        except SupabaseStoreError:
            # Keep the dashboard operational while a sleeping/waking dependency
            # reconnects. The browser retains its last successful snapshot.
            return {
                "items": [],
                "persistent": True,
                "healthy": False,
                "reason": "Persistent merchant memory is temporarily unavailable.",
                "poll_after_ms": 6000,
            }

    return router
