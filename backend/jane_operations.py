"""Operator actions for analyst-requested Jane investigations.

The frozen engine record is never rewritten here. A qualifying analyst-requested
Jane second opinion may be promoted by an operator into the existing persistent
operational decision layer. This keeps model history immutable while allowing the
merchant-facing queue to reflect an explicit human escalation.
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, HTTPException

from backend.supabase_store import SupabaseMerchantStore, SupabaseStoreError
from linkrisk.live_engine import LiveLinkRiskEngine


JANE_OPERATOR_REASON = "ANALYST_JANE_ESCALATED_TO_VERIFY"


def _overlay_payload(
    payload: dict[str, Any],
    *,
    final_action: str,
    routing_reason: str,
    source: str | None,
) -> dict[str, Any]:
    decision = payload.get("decision")
    if not isinstance(decision, dict):
        return payload

    model_action = str(decision.get("action") or "ALLOW")
    model_reason = str(decision.get("routing_reason") or "V5_ONLY")
    payload["operational"] = {
        "model_action": model_action,
        "model_routing_reason": model_reason,
        "final_action": final_action,
        "routing_reason": routing_reason,
        "override": final_action != model_action or routing_reason != model_reason,
        "source": source,
    }
    decision["action"] = final_action
    decision["routing_reason"] = routing_reason
    return payload


def build_jane_operations_router(
    *,
    engine_provider: Callable[[], LiveLinkRiskEngine],
    jsonable: Callable[[Any], Any],
) -> APIRouter:
    router = APIRouter()
    store = SupabaseMerchantStore()

    @router.post("/api/transactions/{transaction_id}/jane-escalate")
    def escalate_jane(transaction_id: str) -> dict[str, Any]:
        """Explicitly promote a qualifying analyst Jane result to operational VERIFY.

        This endpoint is intentionally operator-only at the deployment middleware
        layer. It changes only the existing payment-intelligence row; it does not
        mutate the causal engine, model score, Jane score, graph, or adjudication.
        """
        engine = engine_provider()
        try:
            record = engine.get_record(transaction_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        analyst = record.get("analyst_jane")
        if not isinstance(analyst, dict) or not analyst.get("requested"):
            raise HTTPException(
                status_code=409,
                detail="Ask Jane for an analyst second opinion before escalating this case.",
            )

        score = float(analyst.get("score") or 0.0)
        threshold = float(analyst.get("score_threshold") or 1.0)
        clue_count = int(analyst.get("clue_count") or 0)
        min_clues = int(analyst.get("min_clue_families") or 1)
        candidate = bool(analyst.get("candidate")) and score >= threshold and clue_count >= min_clues
        if not candidate:
            raise HTTPException(
                status_code=409,
                detail="Jane does not cross the frozen score and clue boundaries for escalation.",
            )

        model_action = str(record.get("decision", {}).get("action") or "ALLOW")
        if model_action != "ALLOW":
            raise HTTPException(
                status_code=409,
                detail=f"The frozen runtime already requires {model_action}; no Jane escalation is needed.",
            )

        if not store.enabled:
            raise HTTPException(
                status_code=503,
                detail="Persistent merchant memory is required for an operator decision override.",
            )

        try:
            rows = store._request(
                "GET",
                "linkrisk_payment_intelligence",
                params={
                    "select": "transaction_id,final_action,routing_reason,source",
                    "transaction_id": f"eq.{transaction_id}",
                    "limit": "1",
                },
            ) or []
        except SupabaseStoreError as exc:
            raise HTTPException(status_code=503, detail="Merchant memory is temporarily unavailable.") from exc

        if not rows:
            raise HTTPException(
                status_code=409,
                detail="This transaction has no persistent operational payment row to update.",
            )

        row = rows[0]
        current_action = str(row.get("final_action") or "ALLOW").upper()
        source = str(row.get("source") or "").strip() or None

        # Never downgrade an existing stronger operational action.
        if current_action == "REVIEW":
            return _overlay_payload(
                jsonable(record),
                final_action="REVIEW",
                routing_reason=str(row.get("routing_reason") or "V5_REVIEW_MANDATORY"),
                source=source,
            )

        if current_action != "VERIFY" or str(row.get("routing_reason") or "") != JANE_OPERATOR_REASON:
            try:
                updated = store._request(
                    "PATCH",
                    "linkrisk_payment_intelligence",
                    params={"transaction_id": f"eq.{transaction_id}"},
                    payload={
                        "final_action": "VERIFY",
                        "routing_reason": JANE_OPERATOR_REASON,
                    },
                    prefer="return=representation",
                ) or []
            except SupabaseStoreError as exc:
                raise HTTPException(status_code=503, detail="Could not persist the operator escalation.") from exc
            if not updated:
                raise HTTPException(status_code=409, detail="The operational payment row could not be updated.")

        return _overlay_payload(
            jsonable(record),
            final_action="VERIFY",
            routing_reason=JANE_OPERATOR_REASON,
            source=source,
        )

    return router
