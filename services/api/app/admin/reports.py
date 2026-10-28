"""Admin console: system health, revenue, announcements and alerts."""

import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, literal, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.admin.accounts import Staff, audit
from app.admin.ops import balances
from app.auth import require_admin
from app.db import Session
from app.models import (
    Account,
    Call,
    CallStatus,
    DeliveryStatus,
    LedgerKind,
    Notification,
    NumberStatus,
    PhoneNumber,
    PlatformSetting,
    WalletEntry,
    WebhookDelivery,
)
from app.numbers.renewals import IST
from app.providers import costs, health

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
HEARTBEAT = "worker_heartbeat"  # platform_settings key the worker writes every minute
SILENT_AFTER = timedelta(minutes=3)
ARQ_QUEUE = "arq:queue"
REVENUE_DAYS_MAX = 366


async def beat(factory: async_sessionmaker[AsyncSession], now: datetime) -> None:
    """The worker is alive: written every minute, read by system health and the alerts."""
    async with factory() as session:
        await session.execute(
            insert(PlatformSetting)
            .values(key=HEARTBEAT, value=now.isoformat())
            .on_conflict_do_update(index_elements=["key"], set_={"value": now.isoformat()})
        )
        await session.commit()


async def _last_beat(session: AsyncSession) -> datetime | None:
    row = await session.get(PlatformSetting, HEARTBEAT)
    return datetime.fromisoformat(row.value) if row else None


def _silent(last: datetime | None, now: datetime) -> bool:
    return last is None or now - last > SILENT_AFTER


@router.get("/system")
async def system_health(request: Request, session: Session) -> dict[str, Any]:
    """The database, Redis, the worker's last heartbeat and how much work is waiting."""
    now = datetime.now(UTC)
    started = time.monotonic()
    await session.execute(text("SELECT 1"))
    database_ms = round((time.monotonic() - started) * 1000, 1)
    try:
        started = time.monotonic()
        await request.app.state.redis.ping()
        redis: dict[str, Any] = {"ok": True, "ms": round((time.monotonic() - started) * 1000, 1)}
        redis["jobs_waiting"] = int(await request.app.state.redis.zcard(ARQ_QUEUE))
    except Exception as exc:  # shown, not raised: this page is for when things are broken
        redis = {"ok": False, "error": type(exc).__name__}
    last = await _last_beat(session)

    async def count(*where: Any) -> int:
        return int(await session.scalar(select(func.count()).where(*where)) or 0)

    return {
        "database": {"ok": True, "ms": database_ms},
        "redis": redis,
        "worker": {"last_heartbeat": last, "silent": _silent(last, now)},
        "queues": {
            "calls_due": await count(Call.status == CallStatus.QUEUED, Call.scheduled_for <= now),
            "analysis_waiting": await count(Call.analysis_status == "pending"),
            "webhooks_waiting": await count(WebhookDelivery.status == DeliveryStatus.PENDING),
            "calls_to_reconcile": await count(Call.billing_status == "reconcile"),
        },
    }


@router.get("/revenue")
async def revenue(
    session: Session, days: Annotated[int, Query(ge=1, le=REVENUE_DAYS_MAX)] = 30
) -> dict[str, Any]:
    """Per India day: money in (top-ups), what accounts used (calls, numbers, AI help, less
    refunds; free credits count once they are used), what the vendors cost us at the entered
    rates, and the margin."""
    now = datetime.now(UTC)
    since = now - timedelta(days=days)
    day = func.date(func.timezone("UTC", WalletEntry.created_at) + IST)
    rows = await session.execute(
        select(day, WalletEntry.kind, func.sum(WalletEntry.amount))
        .where(WalletEntry.created_at >= since)
        .group_by(day, WalletEntry.kind)
    )
    zero = Decimal("0")
    out: dict[date, dict[str, Decimal]] = {}

    def at(d: date) -> dict[str, Decimal]:
        keys = ("topups", "calls", "numbers", "ai", "refunds", "provider_cost")
        return out.setdefault(d, dict.fromkeys(keys, zero))

    spent = {
        LedgerKind.CALL: "calls",
        LedgerKind.NUMBER: "numbers",
        LedgerKind.AI_USE: "ai",
    }
    for d, kind, amount in rows:
        if kind is LedgerKind.TOPUP:
            at(d)["topups"] += amount
        elif kind is LedgerKind.REFUND:
            at(d)["refunds"] += amount
        elif kind in spent:
            at(d)[spent[kind]] -= amount
    for usage in await costs.usage(session, since, now, per_day=True):
        if usage.cost is not None and usage.day is not None:
            at(usage.day)["provider_cost"] += usage.cost
    items = []
    for d in sorted(out):
        row = out[d]
        used = row["calls"] + row["numbers"] + row["ai"] - row["refunds"]
        items.append({"day": d, **row, "used": used, "margin": used - row["provider_cost"]})
    return {"days": days, "items": items}


class Announcement(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=1, max_length=4000)


@router.post("/announcements")
async def announce(body: Announcement, staff: Staff, session: Session) -> dict[str, int]:
    """Put a message in every account's notification bell."""
    result = await session.execute(
        insert(Notification).from_select(
            ["id", "account_id", "kind", "title", "body"],
            select(
                func.gen_random_uuid(),
                Account.id,
                literal("announcement"),
                literal(body.title),
                literal(body.body),
            ),
        )
    )
    reached = int(result.rowcount)  # type: ignore[attr-defined]
    audit(session, staff, None, "announcement", title=body.title, accounts=reached)
    await session.commit()
    return {"accounts": reached}


@router.get("/alerts")
async def alerts(session: Session) -> list[dict[str, Any]]:
    """What needs a person now: vendors calls are avoiding, vendor balances running low, numbers
    whose purchase nobody has settled, and a worker that has gone quiet."""
    now = datetime.now(UTC)
    out: list[dict[str, Any]] = [
        {"kind": "provider_unhealthy", "detail": f"{kind} vendor {vendor} is failing"}
        for kind, vendor in sorted(await health.unhealthy(session, now))
    ]
    out += [
        {
            "kind": "provider_balance_low",
            "detail": f"{b['vendor']} has about INR {b['estimated_inr']} left",
        }
        for b in await balances(session, now)
        if b["low"]
    ]
    waiting = await session.scalar(
        select(func.count()).where(PhoneNumber.status == NumberStatus.RECONCILE)
    )
    if waiting:
        out.append(
            {"kind": "numbers_to_reconcile", "detail": f"{waiting} number purchase(s) to settle"}
        )
    last = await _last_beat(session)
    if _silent(last, now):
        seen = last.isoformat() if last else "never"
        out.append({"kind": "worker_silent", "detail": f"the worker was last seen {seen}"})
    return out
