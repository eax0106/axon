import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.account.settings import router as account_router
from app.actions.router import router as actions_router
from app.admin.accounts import router as admin_accounts_router
from app.admin.ops import router as admin_ops_router
from app.admin.reports import router as admin_reports_router
from app.auth import AuthNotConfiguredError, require_admin
from app.auth import router as auth_router
from app.billing.ledger import InsufficientCreditsError
from app.billing.router import router as billing_router
from app.calls.conversations import router as conversations_router
from app.calls.dnc import router as dnc_router
from app.calls.leads import router as leads_router
from app.calls.memory import router as memory_router
from app.calls.notifications import router as notifications_router
from app.calls.stats import router as stats_router
from app.campaigns.lists import router as contact_lists_router
from app.campaigns.panel import router as campaign_panel_router
from app.campaigns.router import router as campaigns_router
from app.developer import hooks  # noqa: F401 - announces new leads and campaign status changes
from app.developer.employee_hook import router as result_webhook_router
from app.developer.public import docs as public_docs_router
from app.developer.public import router as public_api_router
from app.developer.router import router as developer_router
from app.employees.ai import router as ai_router
from app.employees.calls import router as calls_router
from app.employees.router import router as employees_router
from app.inbound.router import router as inbound_router
from app.instant.policy import router as dial_rules_router
from app.instant.public import router as instant_public_router
from app.instant.router import router as instant_router
from app.live import router as live_router
from app.numbers.router import router as numbers_router
from app.phone_verify import router as phone_verify_router
from app.providers.base import ProviderNotConfiguredError
from app.providers.registry import report_all
from app.settings import get_settings
from app.training.router import router as training_router
from app.voices import router as voices_router

READY_TIMEOUT_S = 2.0


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.db = create_async_engine(
        settings.database_url, pool_pre_ping=True, connect_args={"timeout": READY_TIMEOUT_S}
    )
    app.state.redis = Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=READY_TIMEOUT_S,
        socket_timeout=READY_TIMEOUT_S,
    )
    yield
    await app.state.redis.aclose()
    await app.state.db.dispose()


app = FastAPI(title="Axon Voice Engine API", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(live_router)
app.include_router(employees_router)
app.include_router(ai_router)
app.include_router(actions_router)
app.include_router(training_router)
app.include_router(calls_router)
app.include_router(instant_router)
app.include_router(campaigns_router)
app.include_router(campaign_panel_router)
app.include_router(inbound_router)
app.include_router(contact_lists_router)
app.include_router(instant_public_router)
app.include_router(conversations_router)
app.include_router(leads_router)
app.include_router(memory_router)
app.include_router(notifications_router)
app.include_router(stats_router)
app.include_router(voices_router)
app.include_router(billing_router)
app.include_router(numbers_router)
app.include_router(phone_verify_router)
app.include_router(dial_rules_router)
app.include_router(developer_router)
app.include_router(result_webhook_router)
app.include_router(public_api_router)
app.include_router(public_docs_router)
app.include_router(account_router)
app.include_router(dnc_router)
app.include_router(admin_accounts_router)
app.include_router(admin_ops_router)
app.include_router(admin_reports_router)


@app.exception_handler(AuthNotConfiguredError)
async def auth_not_configured(_: Request, __: AuthNotConfiguredError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "error": "auth_not_configured",
            "missing_keys": ["AXON_JWT_SECRET"],
            "detail": "AXON_JWT_SECRET must be set (at least 32 characters)",
        },
    )


@app.exception_handler(ProviderNotConfiguredError)
async def provider_not_configured(_: Request, exc: ProviderNotConfiguredError) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "error": "provider_not_configured",
            "kind": exc.kind,
            "provider": exc.name,
            "missing_keys": exc.missing_keys,
            "detail": exc.detail,
        },
    )


@app.exception_handler(InsufficientCreditsError)
async def insufficient_credits(_: Request, exc: InsufficientCreditsError) -> JSONResponse:
    return JSONResponse(
        status_code=402,
        content={
            "error": "insufficient_credits",
            "balance": str(exc.balance),
            "needed": str(exc.needed),
            "detail": "not enough credits: top up to continue",
        },
    )


@app.exception_handler(httpx.HTTPError)
async def vendor_error(_: Request, exc: httpx.HTTPError) -> JSONResponse:
    """A vendor call failed (rejected key, outage, timeout): 502, never a bare 500."""
    status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
    return JSONResponse(
        status_code=502,
        content={
            "error": "provider_error",
            "vendor_status": status,
            "detail": f"{type(exc).__name__} calling {exc.request.url.host}",
        },
    )


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


async def _check_db(request: Request) -> None:
    async with request.app.state.db.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _check_redis(request: Request) -> None:
    await request.app.state.redis.ping()


@app.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    checks = {"postgres": _check_db(request), "redis": _check_redis(request)}
    results = await asyncio.gather(
        *(asyncio.wait_for(c, READY_TIMEOUT_S) for c in checks.values()), return_exceptions=True
    )
    failed = [name for name, r in zip(checks, results, strict=True) if isinstance(r, BaseException)]
    if failed:
        return JSONResponse(status_code=503, content={"status": "unavailable", "failed": failed})
    return JSONResponse({"status": "ready"})


@app.get("/admin/providers", dependencies=[Depends(require_admin)])
async def admin_providers() -> dict[str, Any]:
    return {"providers": [asdict(r) for r in await report_all()]}
