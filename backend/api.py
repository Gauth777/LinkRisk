"""FastAPI product surface for the frozen LinkRisk live engine."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
import math
import os
from pathlib import Path
import sys
from threading import Lock
import time
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from backend.model_assets import asset_status, ensure_model_assets
from backend.razorpay_checkout import build_checkout_router
from backend.razorpay_integration import (
    MerchantTelemetry,
    RazorpayIntegrationState,
    SUPPORTED_PAYMENT_EVENTS,
    fallback_event_id,
    integration_metadata,
    normalize_payment_to_live_input,
    payment_entity_from_webhook,
    verify_webhook_signature,
)
from linkrisk.engine import FrozenChampionScorer
from linkrisk.live_engine import LiveLinkRiskEngine, LiveTransactionInput
from linkrisk.mentalist_runtime_policy import FrozenMentalistScorer, MentalistRuntimePolicy


VALIDATION_SNAPSHOT = {
    "fraud_capture": 0.4421,
    "fraud_capture_lift_pp": 1.64,
    "legitimate_friction": 0.0464,
    "legitimate_friction_delta_pp": -0.06,
    "intervention_share": 0.0600,
    "mentalist_novel_cases": 519,
    "mentalist_frauds_added": 50,
    "v5_review_precision": 0.5336,
    "held_out_test_status": "sealed",
}


class TransactionRequest(BaseModel):
    amount: float = Field(ge=0)
    payment_profile: str = Field(min_length=1, max_length=120)
    device_info: str = Field(min_length=1, max_length=160)
    receiver_domain: str = Field(min_length=1, max_length=160)
    browser_context: str = Field(min_length=1, max_length=160)
    product_code: str = "W"
    payer_domain: str = "gmail.com"
    device_type: str = "desktop"
    card_network: str = "visa"
    card_type: str = "debit"


class TelemetryRequest(BaseModel):
    reference_id: str = Field(min_length=1, max_length=160)
    payment_profile: str = Field(min_length=1, max_length=120)
    device_info: str = Field(min_length=1, max_length=160)
    browser_context: str = Field(min_length=1, max_length=160)
    receiver_domain: str = Field(default="merchant.local", min_length=1, max_length=160)
    device_type: str = Field(default="unknown", min_length=1, max_length=40)
    product_code: str = Field(default="W", min_length=1, max_length=12)


class AdjudicationRequest(BaseModel):
    outcome: str


class AdvanceTimeRequest(BaseModel):
    seconds: float = Field(gt=0, le=31_536_000)


class EngineService:
    def __init__(self) -> None:
        self._engine: LiveLinkRiskEngine | None = None
        self._lock = Lock()
        self.last_error: str | None = None

    def get(self) -> LiveLinkRiskEngine:
        if self._engine is not None:
            return self._engine
        with self._lock:
            if self._engine is not None:
                return self._engine
            try:
                ensure_model_assets(ROOT)
                champion = FrozenChampionScorer.from_artifacts(ROOT)
                mentalist = FrozenMentalistScorer.from_artifacts(ROOT)
                self._engine = LiveLinkRiskEngine(
                    champion,
                    mentalist_scorer=mentalist,
                    start_time=time.time(),
                )
                self.last_error = None
            except Exception as exc:  # surfaced to /api/health and 503 responses
                self.last_error = f"{type(exc).__name__}: {exc}"
                raise
            return self._engine

    def maybe(self) -> LiveLinkRiskEngine | None:
        return self._engine

    def reset(self) -> None:
        if self._engine is not None:
            self._engine.reset(start_time=time.time())


service = EngineService()
razorpay_state = RazorpayIntegrationState()
app = FastAPI(
    title="LinkRisk API",
    version="1.0.0",
    description="Frozen v0.5 + Mentalist v1.0 payment-risk runtime.",
)

origins = [
    item.strip()
    for item in os.getenv(
        "LINKRISK_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if item.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.generic):
        return _jsonable(value.item())
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _engine_or_503() -> LiveLinkRiskEngine:
    try:
        return service.get()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Frozen model assets are unavailable.",
                "error": f"{type(exc).__name__}: {exc}",
                "asset_status": asset_status(ROOT),
            },
        ) from exc


def _record_payload(engine: LiveLinkRiskEngine, transaction_id: str) -> dict[str, Any]:
    record = engine.get_record(transaction_id)
    return _jsonable(record)


def _razorpay_secret() -> str:
    return os.getenv("RAZORPAY_WEBHOOK_SECRET", "").strip()


app.include_router(
    build_checkout_router(
        state=razorpay_state,
        engine_provider=_engine_or_503,
        jsonable=_jsonable,
    )
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    status = asset_status(ROOT)
    engine_loaded = service.maybe() is not None
    return {
        "ok": status["ready"],
        "engine_loaded": engine_loaded,
        "asset_status": status,
        "last_error": service.last_error,
        "held_out_test": "sealed",
        "razorpay_webhook_configured": bool(_razorpay_secret()),
    }


@app.get("/api/overview")
def overview() -> dict[str, Any]:
    engine = service.maybe()
    live = {
        "transactions": 0,
        "allow": 0,
        "verify": 0,
        "review": 0,
        "clock": 0.0,
    }
    if engine is not None:
        frame = engine.feed()
        if not frame.empty:
            actions = frame["Action"].astype(str)
            live.update(
                {
                    "transactions": int(len(frame)),
                    "allow": int((actions == "ALLOW").sum()),
                    "verify": int((actions == "VERIFY").sum()),
                    "review": int((actions == "REVIEW").sum()),
                    "clock": float(engine.clock),
                }
            )
    return {
        "validation": VALIDATION_SNAPSHOT,
        "live": live,
        "engine_ready": asset_status(ROOT)["ready"],
    }


@app.get("/api/policy")
def policy() -> dict[str, Any]:
    try:
        frozen = MentalistRuntimePolicy.from_artifact(ROOT)
        frozen.validate()
        return _jsonable(asdict(frozen))
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/integrations/razorpay/status")
def razorpay_status() -> dict[str, Any]:
    key_id = os.getenv("RAZORPAY_KEY_ID", "").strip()
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
    return {
        "configured": bool(key_id and key_secret),
        "test_mode": key_id.startswith("rzp_test_"),
        "webhook_configured": bool(_razorpay_secret()),
        "supported_events": sorted(SUPPORTED_PAYMENT_EVENTS),
        "checkout_order_path": "/api/integrations/razorpay/orders",
        "checkout_verify_path": "/api/integrations/razorpay/payments/verify",
        "webhook_path": "/api/webhooks/razorpay",
        "telemetry_path": "/api/integrations/razorpay/telemetry",
        "state": razorpay_state.status(),
        "payer_ip_from_razorpay_used": False,
        "secret_exposed": False,
    }


@app.post("/api/integrations/razorpay/telemetry", status_code=201)
def register_razorpay_telemetry(request: TelemetryRequest) -> dict[str, Any]:
    telemetry = MerchantTelemetry(**request.model_dump())
    razorpay_state.register_telemetry(telemetry)
    return {
        "ok": True,
        "reference_id": telemetry.reference_id,
        "message": "Merchant telemetry registered for Razorpay enrichment.",
    }


@app.post("/api/webhooks/razorpay")
async def razorpay_webhook(request: Request) -> dict[str, Any]:
    """Verify, deduplicate and score Razorpay payment webhooks.

    Signature verification is performed over the exact raw request body before
    JSON parsing. payment.authorized/payment.captured for the same payment are
    payment-deduplicated so an out-of-order second event does not create a second
    LinkRisk transaction.
    """
    secret = _razorpay_secret()
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="RAZORPAY_WEBHOOK_SECRET is not configured.",
        )

    raw_body = await request.body()
    signature = request.headers.get("x-razorpay-signature", "")
    if not verify_webhook_signature(raw_body, signature, secret):
        raise HTTPException(status_code=401, detail="Invalid Razorpay webhook signature.")

    event_id = request.headers.get("x-razorpay-event-id", "").strip() or fallback_event_id(raw_body)
    if not razorpay_state.claim_event(event_id):
        return {"ok": True, "duplicate": True, "event_id": event_id}

    try:
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail="Webhook body is not valid JSON.") from exc

        event_type = str(payload.get("event") or "").strip()
        if event_type not in SUPPORTED_PAYMENT_EVENTS:
            razorpay_state.complete_event(event_id)
            return {
                "ok": True,
                "ignored": True,
                "event_id": event_id,
                "event_type": event_type,
            }

        try:
            payment = payment_entity_from_webhook(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        payment_id = str(payment["id"])
        existing_transaction_id = razorpay_state.transaction_for_payment(payment_id)
        if existing_transaction_id is not None:
            engine = _engine_or_503()
            razorpay_state.complete_event(event_id)
            return {
                "ok": True,
                "duplicate_payment": True,
                "event_id": event_id,
                "event_type": event_type,
                "transaction": _record_payload(engine, existing_transaction_id),
            }

        telemetry = razorpay_state.telemetry_for_payment(payment)
        try:
            live_input = normalize_payment_to_live_input(payment, telemetry)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        engine = _engine_or_503()
        # Arrival time is the causal availability time of the webhook. Never move
        # an explicitly advanced simulation clock backwards.
        engine.clock = max(float(engine.clock), time.time())
        transaction_id = f"RZP-{payment_id}"
        record = engine.score_event(live_input, transaction_id=transaction_id)
        record["integration"] = integration_metadata(
            event_type=event_type,
            event_id=event_id,
            payment=payment,
            telemetry=telemetry,
        )
        razorpay_state.bind_payment(payment_id, transaction_id)
        razorpay_state.complete_event(event_id)
        return {
            "ok": True,
            "duplicate": False,
            "event_id": event_id,
            "event_type": event_type,
            "transaction": _jsonable(record),
        }
    except HTTPException:
        razorpay_state.release_event(event_id)
        raise
    except Exception as exc:
        razorpay_state.release_event(event_id)
        raise HTTPException(
            status_code=500,
            detail=f"Razorpay event processing failed: {type(exc).__name__}: {exc}",
        ) from exc


@app.get("/api/transactions")
def transactions() -> dict[str, Any]:
    engine = service.maybe()
    if engine is None:
        return {"items": [], "clock": 0.0}
    items = []
    for tx_id in engine.transaction_ids:
        record = engine.get_record(tx_id)
        decision = record["decision"]
        mentalist = record.get("mentalist") or {}
        event = record["input"]
        items.append(
            {
                "transaction_id": tx_id,
                "transaction_time": record["transaction_time"],
                "amount": event.amount,
                "profile": event.payment_profile,
                "device": event.device_info,
                "baseline_risk": decision["baseline_risk"],
                "v5_risk": decision["linkrisk_risk"],
                "jane_score": mentalist.get("score"),
                "clue_count": mentalist.get("clue_count", 0),
                "v5_action": decision.get("v5_action", decision["action"]),
                "action": decision["action"],
                "routing_reason": decision.get("routing_reason", "V5_ONLY"),
                "adjudication": engine.adjudication_status(tx_id),
                "integration_source": (record.get("integration") or {}).get("source"),
            }
        )
    return {"items": _jsonable(items), "clock": float(engine.clock)}


@app.post("/api/transactions", status_code=201)
def create_transaction(request: TransactionRequest) -> dict[str, Any]:
    engine = _engine_or_503()

    # The API is a live/manual simulator. Keep its causal clock aligned with
    # actual arrival time so sequential payments become visible as prior history.
    # If the operator has explicitly advanced simulation time (for example 72h
    # to mature adjudication), never move that simulated clock backwards.
    engine.clock = max(float(engine.clock), time.time())

    event = LiveTransactionInput(**request.model_dump())
    record = engine.score_event(event)
    return _jsonable(record)


@app.get("/api/transactions/{transaction_id}")
def transaction(transaction_id: str) -> dict[str, Any]:
    engine = _engine_or_503()
    try:
        return _record_payload(engine, transaction_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/transactions/{transaction_id}/adjudicate")
def adjudicate(transaction_id: str, request: AdjudicationRequest) -> dict[str, Any]:
    engine = _engine_or_503()
    try:
        engine.adjudicate(transaction_id, request.outcome)
        return _record_payload(engine, transaction_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/transactions/{transaction_id}/adjudication")
def clear_adjudication(transaction_id: str) -> dict[str, Any]:
    engine = _engine_or_503()
    try:
        engine.clear_adjudication(transaction_id)
        return _record_payload(engine, transaction_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/session/advance")
def advance_time(request: AdvanceTimeRequest) -> dict[str, Any]:
    engine = _engine_or_503()
    engine.advance_time(request.seconds)
    return {"clock": float(engine.clock)}


@app.post("/api/session/reset")
def reset_session() -> dict[str, Any]:
    service.reset()
    razorpay_state.reset()
    engine = service.maybe()
    return {"ok": True, "clock": float(engine.clock) if engine is not None else time.time()}


# In production the Vite build is copied into frontend/dist by Docker. During
# local frontend development Vite serves the UI and proxies /api to FastAPI.
DIST = ROOT / "frontend" / "dist"
if DIST.exists():
    assets = DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str) -> FileResponse:
        candidate = DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(DIST / "index.html")
