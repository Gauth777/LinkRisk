"""Deployment guardrails for LinkRisk.

No model or persistence semantics live here. The middleware only serialises
stateful runtime mutations, optionally protects operator actions, rate-limits
expensive writes, narrows CORS preflights, and emits compact audit logs.
"""

from __future__ import annotations

import asyncio
from collections import deque
import hashlib
import hmac
import json
import logging
import math
import os
import re
from threading import Lock
import time
from typing import Deque

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response


ADMIN_HEADER = "x-linkrisk-admin"
ALLOWED_METHODS = frozenset({"GET", "POST", "DELETE", "OPTIONS", "HEAD"})
ALLOWED_HEADERS = frozenset({"content-type", ADMIN_HEADER})
ACTION_RE = re.compile(r"^/api/transactions/[^/]+/(deep-investigate|jane-escalate|adjudicate|protect/refund)$")
ADJ_DELETE_RE = re.compile(r"^/api/transactions/[^/]+/adjudication$")
logger = logging.getLogger("uvicorn.error")


def operator_auth_configured() -> bool:
    return bool(os.getenv("LINKRISK_ADMIN_TOKEN", "").strip())


def requires_operator(method: str, path: str) -> bool:
    method = method.upper()
    if method == "POST" and path in {
        "/api/transactions",
        "/api/integrations/razorpay/telemetry",
        "/api/session/advance",
        "/api/session/reset",
        "/api/protection/reset",
    }:
        return True
    if method == "POST" and ACTION_RE.match(path):
        return True
    return bool(method == "DELETE" and ADJ_DELETE_RE.match(path))


def is_serialized_engine_operation(method: str, path: str) -> bool:
    method = method.upper()
    if method == "POST" and path in {
        "/api/integrations/razorpay/payments/verify",
        "/api/webhooks/razorpay",
        "/api/transactions",
        "/api/session/advance",
        "/api/session/reset",
    }:
        return True
    if method == "POST" and re.match(r"^/api/transactions/[^/]+/(deep-investigate|jane-escalate|adjudicate)$", path):
        return True
    return bool(method == "DELETE" and ADJ_DELETE_RE.match(path))


def rate_limit_policy(method: str, path: str) -> tuple[str, int, float] | None:
    method = method.upper()
    if method == "POST" and path == "/api/integrations/razorpay/orders":
        return ("razorpay_orders", 30, 60.0)
    if method == "POST" and path == "/api/integrations/razorpay/payments/verify":
        return ("razorpay_verify", 60, 60.0)
    if method == "POST" and path == "/api/transactions":
        return ("simulator_transactions", 30, 60.0)
    if method == "POST" and path.endswith("/deep-investigate"):
        return ("jane_investigation", 20, 60.0)
    if method == "POST" and path.endswith("/jane-escalate"):
        return ("jane_operator_escalation", 20, 60.0)
    if method == "POST" and path.endswith("/protect/refund"):
        return ("test_refund", 6, 60.0)
    if method == "POST" and path.endswith("/adjudicate"):
        return ("adjudication", 30, 60.0)
    if method == "DELETE" and path.endswith("/adjudication"):
        return ("adjudication", 30, 60.0)
    if method == "POST" and path == "/api/integrations/razorpay/telemetry":
        return ("merchant_telemetry", 60, 60.0)
    if method == "POST" and path in {"/api/session/advance", "/api/session/reset", "/api/protection/reset"}:
        return ("operator_runtime", 30, 60.0)
    return None


def _client_key(request: Request) -> str:
    host = request.client.host if request.client is not None else "unknown"
    agent = request.headers.get("user-agent", "")[:160]
    return hashlib.sha256(f"{host}|{agent}".encode()).hexdigest()[:20]


def _audit(event: str, **fields: object) -> None:
    logger.info("linkrisk_audit %s", json.dumps({"event": event, **fields}, separators=(",", ":"), default=str))


class SlidingWindowLimiter:
    def __init__(self, max_keys: int = 4096) -> None:
        self._lock = Lock()
        self._events: dict[tuple[str, str], Deque[float]] = {}
        self._max_keys = max_keys

    def allow(
        self,
        *,
        scope: str,
        client_key: str,
        limit: int,
        window_seconds: float,
        now: float | None = None,
    ) -> tuple[bool, int]:
        current = time.monotonic() if now is None else float(now)
        cutoff = current - window_seconds
        key = (scope, client_key)
        with self._lock:
            queue = self._events.setdefault(key, deque())
            while queue and queue[0] <= cutoff:
                queue.popleft()
            if len(queue) >= limit:
                return False, max(int(math.ceil(queue[0] + window_seconds - current)), 1)
            queue.append(current)
            if len(self._events) > self._max_keys:
                for stale in list(self._events):
                    if stale != key and (not self._events[stale] or self._events[stale][-1] <= cutoff):
                        self._events.pop(stale, None)
                    if len(self._events) <= self._max_keys:
                        break
        return True, 0


class LinkRiskHardeningMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._engine_lock = asyncio.Lock()
        self._limiter = SlidingWindowLimiter()

    @staticmethod
    def _operator_authorized(request: Request) -> bool:
        configured = os.getenv("LINKRISK_ADMIN_TOKEN", "").strip()
        if not configured:
            return True  # backward-compatible until the operator enables it
        provided = request.headers.get(ADMIN_HEADER, "").strip()
        return bool(provided) and hmac.compare_digest(configured, provided)

    @staticmethod
    def _preflight_error(request: Request) -> str | None:
        if request.method.upper() != "OPTIONS":
            return None
        requested_method = request.headers.get("access-control-request-method", "").upper()
        if requested_method and requested_method not in ALLOWED_METHODS:
            return "CORS method is not allowed"
        requested_headers = {
            value.strip().lower()
            for value in request.headers.get("access-control-request-headers", "").split(",")
            if value.strip()
        }
        return "CORS request contains unsupported headers" if requested_headers - ALLOWED_HEADERS else None

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        path, method = request.url.path, request.method.upper()
        if not path.startswith("/api/"):
            return await call_next(request)

        cors_error = self._preflight_error(request)
        if cors_error:
            _audit("cors_rejected", method=method, path=path)
            return JSONResponse({"detail": cors_error}, status_code=400)
        if method not in ALLOWED_METHODS:
            return JSONResponse({"detail": "Method not allowed"}, status_code=405)

        if requires_operator(method, path) and not self._operator_authorized(request):
            _audit("operator_auth_rejected", method=method, path=path)
            return JSONResponse(
                {"detail": "Operator authorization required."},
                status_code=401,
                headers={"Cache-Control": "no-store"},
            )

        policy = rate_limit_policy(method, path)
        if policy:
            scope, limit, window = policy
            allowed, retry = self._limiter.allow(
                scope=scope,
                client_key=_client_key(request),
                limit=limit,
                window_seconds=window,
            )
            if not allowed:
                _audit("rate_limited", scope=scope, method=method, path=path)
                return JSONResponse(
                    {"detail": "Too many requests. Retry shortly."},
                    status_code=429,
                    headers={"Retry-After": str(retry)},
                )

        serialized = is_serialized_engine_operation(method, path)
        started = time.perf_counter()
        try:
            if serialized:
                async with self._engine_lock:
                    response = await call_next(request)
            else:
                response = await call_next(request)
        except Exception:
            _audit("api_exception", method=method, path=path, serialized=serialized)
            raise

        response.headers["X-LinkRisk-Operator-Protection"] = (
            "configured" if operator_auth_configured() else "compatibility"
        )
        if serialized or requires_operator(method, path) or response.status_code >= 400:
            _audit(
                "api_request",
                method=method,
                path=path,
                status=response.status_code,
                serialized=serialized,
                latency_ms=round((time.perf_counter() - started) * 1000, 1),
            )
        return response
