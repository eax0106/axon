"""The Instant dialer: place due calls, and decide what each ended call means.

`dial_due` and `settle` are plain functions of the database, the telephony adapter and `now`, so
the worker only has to call them on a timer and the tests can run a lead through a whole day.

A call row is the queue entry: status `queued` with `scheduled_for` set is waiting for its time,
`queued` with `scheduled_for` NULL is held (until someone redials), `ringing` has been handed to
the carrier. A call that ends unanswered (busy, no answer, failed) gets its next attempt as a
new row, scheduled by the retry ladder, until the 10th attempt.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.instant import policy, rules
from app.instant.rules import DialerSettings
from app.models import (
    Account,
    Call,
    CallEvent,
    CallStatus,
    Channel,
    DncEntry,
    Employee,
    EmployeeStatus,
    Lead,
    PhoneNumber,
)
from app.providers.base import CallDetail, TelephonyProvider
from app.settings import api_public_url, engine_public_url

BATCH = 20
NOT_READY_RETRY = timedelta(minutes=5)  # a live-employee check that failed: look again later
RINGING_TIMEOUT = timedelta(minutes=3)  # no end callback by then: ask the carrier what happened
GIVE_UP_AFTER = timedelta(minutes=15)  # the carrier never reported: count the attempt as failed


@dataclass(frozen=True)
class Dialed:
    call_id: object
    outcome: str  # dialed, rescheduled, held, cancelled, failed


def outcome_of(detail: CallDetail) -> CallStatus:
    """Map the carrier's record to a call status. Talk time above zero means answered."""
    if detail.answered:
        return CallStatus.COMPLETED
    cause = detail.hangup_cause.upper()
    if cause == "USER_BUSY":
        return CallStatus.BUSY
    if cause in ("NO_ANSWER", "ORIGINATOR_CANCEL", "NO_USER_RESPONSE"):
        return CallStatus.NO_ANSWER
    return CallStatus.FAILED


async def _event(session: AsyncSession, call: Call, kind: str, **data: object) -> None:
    session.add(CallEvent(call_id=call.id, type=kind, data=data))


async def settle(
    session: AsyncSession,
    call: Call,
    status: CallStatus,
    now: datetime,
    duration_s: int | None = None,
) -> Call | None:
    """Record how an attempt ended and, if it was not answered and the ladder allows, queue the
    next attempt. Returns the next attempt, if any. Does not commit."""
    if call.status in (
        CallStatus.COMPLETED,
        CallStatus.BUSY,
        CallStatus.NO_ANSWER,
        CallStatus.FAILED,
    ):
        return None  # already settled: callbacks arrive more than once
    call.status = status
    call.ended_at = now
    call.duration_s = duration_s
    if status is CallStatus.COMPLETED or call.lead_id is None or call.employee_id is None:
        return None
    employee = await session.get(Employee, call.employee_id)
    account = await session.get(Account, call.account_id)
    if employee is None or account is None:
        return None
    settings = DialerSettings.model_validate(employee.dialer or {})
    if not rules.has_retry(call.attempt, settings):
        await _event(session, call, "attempts_used_up", attempts=call.attempt)
        return None
    at = rules.retry_time(call.attempt, now, settings, account.utc_offset_minutes)
    nxt = Call(
        account_id=call.account_id,
        employee_id=call.employee_id,
        lead_id=call.lead_id,
        direction=call.direction,
        channel=call.channel,
        status=CallStatus.QUEUED,
        scheduled_for=at,
        attempt=call.attempt + 1,
    )
    session.add(nxt)
    await session.flush()
    return nxt


async def dial_due(
    factory: async_sessionmaker[AsyncSession],
    telephony: TelephonyProvider,
    now: datetime,
    *,
    limit: int = BATCH,
) -> list[Dialed]:
    """Place every call that is due. Raises ProviderNotConfiguredError (503) if the public URLs
    the carrier needs are not set; the caller gets the telephony adapter from the registry."""
    engine_url, api_url = engine_public_url(), api_public_url()
    claimed = await _claim(factory, now, limit)
    results = [Dialed(c.call_id, c.outcome) for c in claimed if c.outcome != "dial"]
    for item in (c for c in claimed if c.outcome == "dial"):
        answer = f"{engine_url}/vobiz/answer?employee={item.employee_id}&call={item.call_id}"
        hangup = f"{api_url}/vobiz/events"
        try:
            carrier_id = await telephony.originate(item.from_number, item.to_phone, answer, hangup)
        except Exception as exc:
            async with factory() as session:
                call = await session.get(Call, item.call_id)
                assert call is not None
                await _event(session, call, "dial_failed", error=type(exc).__name__)
                await settle(session, call, CallStatus.FAILED, now)
                await session.commit()
            results.append(Dialed(item.call_id, "failed"))
            continue
        async with factory() as session:
            await session.execute(
                update(Call).where(Call.id == item.call_id).values(carrier_call_id=carrier_id)
            )
            await session.commit()
        results.append(Dialed(item.call_id, "dialed"))
    return results


@dataclass(frozen=True)
class _Claim:
    call_id: object
    outcome: str
    employee_id: object = None
    from_number: str = ""
    to_phone: str = ""


async def _claim(
    factory: async_sessionmaker[AsyncSession], now: datetime, limit: int
) -> list[_Claim]:
    """Decide every due call in one transaction, locking the rows so two workers never take the
    same one, and mark the ones to dial as ringing before any slow carrier call."""
    out: list[_Claim] = []
    async with factory() as session:
        due = await session.scalars(
            select(Call)
            .where(
                Call.status == CallStatus.QUEUED,
                Call.channel == Channel.INSTANT,
                Call.is_test.is_(False),
                Call.scheduled_for.is_not(None),
                Call.scheduled_for <= now,
            )
            .order_by(Call.scheduled_for)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        for call in due:
            out.append(await _decide(session, call, now))
        await session.commit()
    return out


async def _decide(session: AsyncSession, call: Call, now: datetime) -> _Claim:
    employee = await session.get(Employee, call.employee_id) if call.employee_id else None
    lead = await session.get(Lead, call.lead_id) if call.lead_id else None
    account = await session.get(Account, call.account_id)
    if employee is None or lead is None or account is None:
        call.status = CallStatus.CANCELED
        await _event(session, call, "cancelled", reason="employee or lead no longer exists")
        return _Claim(call.id, "cancelled")
    on_dnc = await session.scalar(
        select(DncEntry.id).where(
            DncEntry.account_id == call.account_id, DncEntry.phone == lead.phone
        )
    )
    if on_dnc:  # checked before every dial, not only at intake
        call.status = CallStatus.CANCELED
        await _event(session, call, "cancelled", reason="number is on the do-not-call list")
        return _Claim(call.id, "cancelled")
    number = await session.get(PhoneNumber, employee.number_id) if employee.number_id else None
    if employee.status is not EmployeeStatus.LIVE or number is None:
        call.scheduled_for = now + NOT_READY_RETRY
        return _Claim(call.id, "rescheduled")
    settings = DialerSettings.model_validate(employee.dialer or {})
    if not rules.in_window(now, settings, account.utc_offset_minutes):
        call.scheduled_for = rules.adjust(now, settings, account.utc_offset_minutes)
        await _event(session, call, "outside_window", next=str(call.scheduled_for))
        return _Claim(call.id, "held" if call.scheduled_for is None else "rescheduled")
    verdict = policy.check_dial(employee, number, lead.phone)
    if not verdict.allowed:
        call.status = CallStatus.CANCELED
        await _event(session, call, "cancelled", reason=verdict.reason)
        return _Claim(call.id, "cancelled")
    call.status = CallStatus.RINGING
    call.started_at = now
    call.number_id = number.id
    return _Claim(call.id, "dial", employee.id, number.e164, lead.phone)


async def settle_from_carrier(
    factory: async_sessionmaker[AsyncSession],
    telephony: TelephonyProvider,
    call_id: object,
    now: datetime,
) -> str:
    """Ask the carrier how a call went and settle it. 'pending' if its record is not there yet."""
    async with factory() as session:
        call = await session.get(Call, call_id)
        if call is None or call.carrier_call_id is None:
            return "unknown"
        detail = await telephony.call_detail(call.carrier_call_id)
        if detail is None:
            return "pending"
        await settle(session, call, outcome_of(detail), now, detail.duration_s)
        await session.commit()
        return "settled"


async def reap_stale(
    factory: async_sessionmaker[AsyncSession], telephony: TelephonyProvider, now: datetime
) -> int:
    """Calls still ringing long after they were placed: no end callback came. Ask the carrier;
    a call it never reports on counts as a failed attempt so the lead is not lost."""
    async with factory() as session:
        stale = list(
            await session.scalars(
                select(Call).where(
                    Call.status == CallStatus.RINGING,
                    Call.started_at < now - RINGING_TIMEOUT,
                    Call.is_test.is_(False),
                )
            )
        )
    reaped = 0
    for call in stale:
        state = await settle_from_carrier(factory, telephony, call.id, now)
        too_old = call.started_at is not None and call.started_at < now - GIVE_UP_AFTER
        if state in ("pending", "unknown") and too_old:
            async with factory() as session:
                row = await session.get(Call, call.id)
                assert row is not None
                await _event(session, row, "no_carrier_report")
                await settle(session, row, CallStatus.FAILED, now)
                await session.commit()
            state = "settled"
        reaped += state == "settled"
    return reaped
