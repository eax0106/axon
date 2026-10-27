"""The auto call-back to a caller we could not answer: one, inside calling hours, never to a number
on the do-not-call list.

It is an ordinary queued call row that the Instant dialer places, under the `callback` rule of the
rule table, and it is never retried: one try is what the owner switched on.
"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.inbound.settings import InboundSettings
from app.instant import rules
from app.instant.rules import DialerSettings
from app.models import Call, CallEvent, CallStatus, Channel, Direction, DncEntry, Employee, Lead

# A caller who found the line shut or busy is called back. One who found the employee paused or
# the account out of credits is not: the dialer would only wait for those to change, perhaps days.
AUTO_CODES = ("closed", "busy")
ONCE_PER = timedelta(days=1)
DIALED_CHANNELS = (Channel.INSTANT, Channel.INBOUND)  # a Bulk employee's callers are its campaign's


async def schedule_auto(
    session: AsyncSession,
    missed: Call,
    employee: Employee,
    settings: InboundSettings,
    code: str,
    now: datetime,
) -> Call | None:
    """Queue the call-back for a missed call, or say in its timeline why not. Does not commit."""
    if not settings.auto_callback or code not in AUTO_CODES:
        return None
    if employee.channel not in DIALED_CHANNELS or employee.number_id is None:
        return None
    lead = await session.get(Lead, missed.lead_id) if missed.lead_id else None
    if lead is None:  # a withheld, foreign or landline number cannot be called by the dialer
        await _skip(session, missed, "the caller's number cannot be called back")
        return None
    if await session.scalar(
        select(DncEntry.id).where(
            DncEntry.account_id == missed.account_id, DncEntry.phone == lead.phone
        )
    ):
        await _skip(session, missed, "the number is on the do-not-call list")
        return None
    recent = await session.scalar(
        select(Call.id).where(
            Call.account_id == missed.account_id,
            Call.lead_id == lead.id,
            Call.callback_of_id.is_not(None),
            Call.created_at > now - ONCE_PER,
        )
    )
    if recent is not None:
        await _skip(session, missed, "this caller was already called back today")
        return None
    at = rules.next_window_start(
        now + timedelta(minutes=1), DialerSettings.model_validate(employee.dialer or {}), rules.IST
    )
    callback = Call(
        account_id=missed.account_id,
        employee_id=employee.id,
        lead_id=lead.id,
        direction=Direction.OUTBOUND,
        channel=employee.channel,
        status=CallStatus.QUEUED,
        scheduled_for=at,
        attempt=1,
        is_callback=True,
        callback_of_id=missed.id,
        created_at=now,
    )
    session.add(callback)
    session.add(
        CallEvent(call_id=missed.id, type="auto_callback_scheduled", data={"at": at.isoformat()})
    )
    return callback


async def _skip(session: AsyncSession, missed: Call, why: str) -> None:
    session.add(CallEvent(call_id=missed.id, type="auto_callback_skipped", data={"reason": why}))
