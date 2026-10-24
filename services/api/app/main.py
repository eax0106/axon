import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.providers.registry import ProviderNotConfiguredError, report_all
from app.settings import get_settings

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


@app.get("/admin/providers")
async def admin_providers() -> dict[str, Any]:
    # ponytail: unauthenticated until B1 adds auth and roles; exposes key names, never values.
    return {"providers": [asdict(r) for r in await report_all()]}
