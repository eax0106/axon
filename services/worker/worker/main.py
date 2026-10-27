"""Arq worker: the Instant dialer, the post-call analysis and the Sheets lead poller.

Run: `arq worker.main.WorkerSettings`. Health: `arq --check worker.main.WorkerSettings`.
Every tick is a plain function of the database and `now` (app.instant), so the worker is only
the clock: it opens a session factory and calls them on a timer.
"""

import logging
import os
from datetime import UTC, datetime
from typing import Any

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.billing import alerts, metering
from app.calls import postcall
from app.instant import dialer
from app.instant.sheets import poll_all
from app.numbers import renewals
from app.providers.base import (
    ProviderKind,
    ProviderNotConfiguredError,
    SheetsProvider,
    TelephonyProvider,
)
from app.providers.registry import require
from app.settings import get_settings

log = logging.getLogger("axon.worker")


async def ping(_ctx: dict[str, Any]) -> str:
    # ponytail: arq refuses a worker with no functions; ping also serves as a liveness probe.
    return "pong"


async def startup(ctx: dict[str, Any]) -> None:
    engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    ctx["db"] = engine
    ctx["factory"] = async_sessionmaker(engine, expire_on_commit=False)


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["db"].dispose()


def _factory(ctx: dict[str, Any]) -> async_sessionmaker[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = ctx["factory"]
    return factory


async def dial_tick(ctx: dict[str, Any]) -> int:
    """Every few seconds: place the calls that are due."""
    try:
        telephony = require(ProviderKind.TELEPHONY)
        assert isinstance(telephony, TelephonyProvider)
        placed = await dialer.dial_due(_factory(ctx), telephony, datetime.now(UTC))
    except ProviderNotConfiguredError as exc:
        log.warning(f"dialer idle: {exc.detail}")  # missing key or URL: nothing pretends to work
        return 0
    return len(placed)


async def reap_tick(ctx: dict[str, Any]) -> int:
    """Every minute: settle calls whose end callback never came, and close test calls that never
    finished (an unused browser ticket, a call whose setup failed)."""
    now = datetime.now(UTC)
    reaped = await postcall.reap_test_calls(_factory(ctx), now)
    try:
        telephony = require(ProviderKind.TELEPHONY)
        assert isinstance(telephony, TelephonyProvider)
    except ProviderNotConfiguredError:
        return reaped
    return reaped + await dialer.reap_stale(_factory(ctx), telephony, now)


async def billing_tick(ctx: dict[str, Any]) -> int:
    """Every half minute: charge finished calls from the carrier's own record."""
    try:
        telephony = require(ProviderKind.TELEPHONY)
        assert isinstance(telephony, TelephonyProvider)
    except ProviderNotConfiguredError:
        return 0
    counts = await metering.bill_pending(_factory(ctx), telephony, datetime.now(UTC))
    return counts["billed"] + counts["free"] + counts["reconcile"]


async def low_balance_tick(ctx: dict[str, Any]) -> int:
    """Every half minute: email the accounts whose balance just dropped under the threshold."""
    return await alerts.send_pending(_factory(ctx))


async def renewal_tick(ctx: dict[str, Any]) -> int:
    """Every ten minutes: rent for numbers that are due, grace for those that cannot pay, release
    for those whose grace is over."""
    counts = await renewals.renew_due(_factory(ctx), datetime.now(UTC))
    return sum(counts.values())


async def post_call_tick(ctx: dict[str, Any]) -> int:
    """Every few seconds: analyse calls that just ended (summary, outcome, captured fields)."""
    return await postcall.process_pending(_factory(ctx), datetime.now(UTC))


async def sheets_tick(ctx: dict[str, Any]) -> int:
    """Every minute: take new rows from connected Google Sheets."""
    try:
        sheets = require(ProviderKind.SHEETS)
        assert isinstance(sheets, SheetsProvider)
    except ProviderNotConfiguredError:
        return 0
    return await poll_all(_factory(ctx), sheets, datetime.now(UTC))


class WorkerSettings:
    functions = (ping,)
    cron_jobs = (
        cron(dial_tick, second=set(range(0, 60, 3)), run_at_startup=False, timeout=50),
        cron(post_call_tick, second=set(range(5, 60, 10)), run_at_startup=False, timeout=240),
        cron(billing_tick, second={25, 55}, run_at_startup=False, timeout=120),
        cron(low_balance_tick, second={10, 40}, run_at_startup=False, timeout=120),
        cron(
            renewal_tick, minute=set(range(0, 60, 10)), second=35, run_at_startup=False, timeout=240
        ),
        cron(reap_tick, second=15, run_at_startup=False, timeout=50),
        cron(sheets_tick, second=45, run_at_startup=False, timeout=50),
    )
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    health_check_interval = 10
