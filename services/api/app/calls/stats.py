"""Dashboard numbers, computed from the calls themselves.

Definitions (so a number can be checked by hand):
  placed      outbound calls that reached a final result (completed, no answer, busy, failed)
  connected   calls where a person answered (status completed)
  qualified   connected calls whose outcome is interested or callback_requested
  converted   connected calls whose outcome is interested
  connect %   connected outbound / placed outbound      qualify %    qualified / connected
  conversion %  converted / connected
Test calls and calls still waiting or ringing are not counted. Hours are Indian time.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import and_, func, select

from app.auth import CurrentUser
from app.db import Session
from app.models import (
    Call,
    CallStatus,
    Direction,
    Employee,
    IntakeStatus,
    LeadIntakeEntry,
)

router = APIRouter()
FINAL = (CallStatus.COMPLETED, CallStatus.NO_ANSWER, CallStatus.BUSY, CallStatus.FAILED)
QUALIFIED = ("interested", "callback_requested")
MIN_CALLS_FOR_BEST_HOUR = 5
SPEED_TARGET_S = 60
RANGES = {"7d": 7, "30d": 30, "90d": 90}


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _window(
    range_: str, date_from: datetime | None, date_to: datetime | None
) -> tuple[datetime, datetime]:
    if range_ == "custom":
        if not (date_from and date_to) or date_to <= date_from:
            raise HTTPException(422, "a custom range needs date_from before date_to")
        return date_from, date_to
    end = date_to or datetime.now(UTC)
    return end - timedelta(days=RANGES[range_]), end


@router.get("/stats/overview")
async def overview(
    user: CurrentUser,
    session: Session,
    range: Annotated[Literal["7d", "30d", "90d", "custom"], Query()] = "7d",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> dict[str, Any]:
    start, end = _window(range, date_from, date_to)

    def scoped(query: Any) -> Any:
        return query.where(
            Call.account_id == user.account_id,
            Call.is_test.is_(False),
            Call.status.in_(FINAL),
            Call.created_at >= start,
            Call.created_at < end,
        )

    connected = Call.status == CallStatus.COMPLETED
    outbound = Call.direction == Direction.OUTBOUND
    qualified = and_(connected, Call.outcome.in_(QUALIFIED))
    converted = and_(connected, Call.outcome == "interested")

    def count_if(condition: Any) -> Any:
        return func.count().filter(condition)

    totals = (
        await session.execute(
            scoped(
                select(
                    func.count(),
                    count_if(and_(outbound)),
                    count_if(and_(connected, outbound)),
                    count_if(connected),
                    count_if(qualified),
                    count_if(converted),
                )
            )
        )
    ).one()
    calls, placed, connected_out, connected_all, qualified_n, converted_n = (int(v) for v in totals)

    channels = (
        await session.execute(scoped(select(Call.channel, func.count()).group_by(Call.channel)))
    ).all()
    # The hour the call was placed (a retry or callback is created long before it is dialed).
    dialed_at = func.coalesce(Call.started_at, Call.created_at)
    ist_hour = func.extract("hour", dialed_at.op("AT TIME ZONE")("Asia/Kolkata"))
    hours = (
        await session.execute(
            scoped(select(ist_hour, count_if(outbound), count_if(and_(connected, outbound))))
            .where(outbound)
            .group_by(ist_hour)
            .order_by(ist_hour)
        )
    ).all()
    by_hour: list[dict[str, Any]] = [
        {
            "hour": int(h),
            "placed": int(p),
            "connected": int(c),
            "connect_rate": _rate(int(c), int(p)),
        }
        for h, p, c in hours
    ]
    eligible = [h for h in by_hour if h["placed"] >= MIN_CALLS_FOR_BEST_HOUR]
    best = max(eligible, key=lambda h: (h["connect_rate"] or 0.0, h["placed"]), default=None)

    board = (
        await session.execute(
            scoped(
                select(
                    Employee.id,
                    Employee.name,
                    count_if(outbound),
                    count_if(connected),
                    count_if(qualified),
                    count_if(converted),
                ).join(Employee, Employee.id == Call.employee_id)
            )
            .group_by(Employee.id, Employee.name)
            .order_by(count_if(converted).desc(), count_if(connected).desc(), Employee.name)
        )
    ).all()

    speed = await _speed(session, user.account_id, start, end)
    return {
        "range": range,
        "from": start,
        "to": end,
        "totals": {
            "calls": calls,
            "placed": placed,
            "connected": connected_all,
            "qualified": qualified_n,
            "converted": converted_n,
        },
        "rates": {
            "connect": _rate(connected_out, placed),
            "qualify": _rate(qualified_n, connected_all),
            "conversion": _rate(converted_n, connected_all),
        },
        "channel_split": {c.value: int(n) for c, n in channels},
        "by_hour": by_hour,
        "best_hour": best["hour"] if best else None,
        "leaderboard": [
            {
                "employee_id": e,
                "name": name,
                "placed": int(p),
                "connected": int(c),
                "qualified": int(q),
                "converted": int(v),
            }
            for e, name, p, c, q, v in board
        ],
        "speed": speed,
    }


async def _speed(session: Any, account_id: Any, start: datetime, end: datetime) -> dict[str, Any]:
    """Instant leads: how many got their first call within a minute of arriving."""
    delay = Call.started_at - LeadIntakeEntry.created_at
    row = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(delay <= timedelta(seconds=SPEED_TARGET_S)),
            )
            .select_from(LeadIntakeEntry)
            .join(Call, Call.id == LeadIntakeEntry.call_id, isouter=True)
            .where(
                LeadIntakeEntry.account_id == account_id,
                LeadIntakeEntry.status == IntakeStatus.ACCEPTED,
                LeadIntakeEntry.source != "test",
                LeadIntakeEntry.created_at >= start,
                LeadIntakeEntry.created_at < end,
            )
        )
    ).one()
    accepted, within = int(row[0]), int(row[1])
    return {"accepted": accepted, "within_60s": within, "rate": _rate(within, accepted)}
