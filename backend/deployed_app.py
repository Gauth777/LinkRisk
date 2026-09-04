"""Deployment entrypoint that warms the frozen LinkRisk runtime before serving.

Render starts a fresh filesystem. Importing this module triggers the same
EngineService used by the API, which downloads/verifies the frozen model bundle
when needed and loads the v2 live engine in the Uvicorn process. A warmup
failure is retained in ``service.last_error`` so /api/health stays reachable and
surfaces the deployment problem instead of crashing the web service.
"""

from pathlib import Path

from backend.api import _jsonable, app, service
from backend.hardening import LinkRiskHardeningMiddleware
from backend.jane_operations import build_jane_operations_router
from backend.merchant_dashboard import build_merchant_dashboard_router
from backend.protection import build_protection_router

ROOT = Path(__file__).resolve().parents[1]
app.include_router(
    build_protection_router(
        engine_provider=service.get,
        root=ROOT,
    )
)
app.include_router(build_merchant_dashboard_router())
app.include_router(
    build_jane_operations_router(
        engine_provider=service.get,
        jsonable=_jsonable,
    )
)

# Keep operational hardening outside the ML/runtime implementation so scoring,
# persistence semantics and the React product surface remain unchanged.
app.add_middleware(LinkRiskHardeningMiddleware)

try:
    service.get()
except Exception:
    # EngineService records the concrete exception in service.last_error.
    # Keep the HTTP surface alive so deployment health can report it.
    pass
