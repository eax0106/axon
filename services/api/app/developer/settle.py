"""Tell the webhooks about calls that have settled.

Calls are finished by four writers (the dialer, the carrier's callback, the engine, inbound
routing), so instead of hooking each, this looks at the calls that ended and were not announced,
and announces each once. An answered call waits for its analysis, because the summary and the
outcome are the point of the event; if the analysis never comes the call goes out without it."""

from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.developer import events, shapes
from app.models import Call, CallStatus, Direction, Lead

FINAL = (CallStatus.COMPLETED, CallStatus.NO_ANSWER, CallStatus.BUSY, CallStatus.FAILED)
ANALYSED = ("done", "skipped", "failed")
WAIT_FOR_ANALYSIS = timedelta(minutes=20)
BATCH = 50


def connected(call: Call) -> bool:
    return call.status is CallStatus.COMPLETED or call.answered_at is not None


def event_type(call: Call) -> str:
    inbound = call.direction is Direction.INBOUND
    if connected(call):
        return events.INBOUND_ANSWERED if inbound else events.CALL_COMPLETED
    return events.INBOUND_MISSED if inbound else events.CALL_NOT_CONNECTED


async def settle_calls(factory: async_sessionmaker[AsyncSession], now: datetime) -> int:
    """Announce the calls that are ready. Returns how many were taken."""
    answered = or_(Call.status == CallStatus.COMPLETED, Call.answered_at.is_not(None))
    async with factory() as session:
        calls = list(
            await session.scalars(
                select(Call)
                .where(
                    Call.events_emitted_at.is_(None),
                    Call.ended_at.is_not(None),
                    Call.is_test.is_(False),
                    Call.status.in_(FINAL),
                    or_(
                        ~answered,
                        Call.analysis_status.in_(ANALYSED),
                        Call.ended_at < now - WAIT_FOR_ANALYSIS,
                    ),
                )
                .order_by(Call.ended_at)
                .limit(BATCH)
                .with_for_update(skip_locked=True)
            )
        )
        await _announce(session, calls, now)
        await session.commit()
    return len(calls)


async def _announce(session: AsyncSession, calls: list[Call], now: datetime) -> None:
    ids = {c.lead_id for c in calls if c.lead_id}
    found = await session.execute(select(Lead.id, Lead.phone).where(Lead.id.in_(ids)))
    phones = {lead_id: phone for lead_id, phone in found.all()}
    for call in calls:
        phone = call.caller_phone or (phones.get(call.lead_id) if call.lead_id else None)
        data = {"call": shapes.call_out(call, phone).model_dump(mode="json")}
        events.record(session, call.account_id, event_type(call), data, call.employee_id)
        call.events_emitted_at = now
