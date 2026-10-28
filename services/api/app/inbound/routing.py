"""What happens when a call arrives on one of our numbers.

The carrier fetches the engine's answer URL; the engine asks `route` what to do. The answer is one
of: answer it (a call row is made, holding one channel of the number), or miss it (a call row
records who rang and why nobody answered). The checks are the ones an outgoing call gets, turned
round: the employee must be live, the account must have credits, the rule table must allow
answering on this number, the business must be open (or take messages), and a channel must be
free.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.billing import policy as credit_policy
from app.inbound import callbacks
from app.inbound.settings import InboundSettings, is_open
from app.inbound.settings import of as inbound_of
from app.instant import policy
from app.instant.intake import normalize_phone
from app.models import (
    Call,
    CallEvent,
    CallStatus,
    Channel,
    Direction,
    Employee,
    EmployeeStatus,
    Lead,
    Notification,
    NumberStatus,
    PhoneNumber,
)
from app.numbers import channels
from app.providers import failover
from app.providers.base import TelephonyProvider

ANSWERABLE = (NumberStatus.ACTIVE, NumberStatus.GRACE)  # a number in grace is still rented
BLOCKED_NOTE_EVERY = timedelta(hours=6)
UNATTACHED = "no AI employee is attached to this number"
NOT_LIVE = "the employee was paused, so it did not answer"
NO_CALLS = "this employee only makes calls: it is set not to answer incoming calls"
CLOSED = "outside opening hours, and the employee is set not to answer then"
BUSY = "every line of the number was already on a call"


@dataclass(frozen=True)
class Routed:
    kind: Literal["answer", "missed", "unknown"]
    call_id: uuid.UUID | None = None
    employee_id: uuid.UUID | None = None
    language: str = "en"
    closed: bool = False
    reason: str | None = None
    code: str | None = None  # a short name for the reason (busy, closed, paused, ...)


def caller_number(raw: str) -> str | None:
    """The caller's number as the carrier gave it (digits, with +), or None for a withheld or
    malformed one."""
    digits = re.sub(r"\D", "", raw)
    return f"+{digits}" if 8 <= len(digits) <= 15 else None


def e164(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    return f"+{digits}"


async def route(
    factory: async_sessionmaker[AsyncSession],
    telephony: TelephonyProvider,
    *,
    to: str,
    caller: str,
    carrier_id: str,
    now: datetime,
) -> Routed:
    """Decide an incoming call. Asking twice about the same carrier call gives the same answer."""
    if not carrier_id or not await telephony.is_live(carrier_id):
        return Routed("unknown")  # a request for a call the carrier does not have is not believed
    async with factory() as session:
        # One decision per carrier call: a retry of the fetch waits here and then finds the row.
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"inbound:{carrier_id}"}
        )
        found = await session.scalar(select(Call).where(Call.carrier_leg_id == carrier_id))
        if found is not None:
            return await _again(session, found)
        routed = await _decide(session, to=e164(to), caller=caller, carrier_id=carrier_id, now=now)
        await session.commit()
        return routed


async def _again(session: AsyncSession, call: Call) -> Routed:
    employee = await session.get(Employee, call.employee_id) if call.employee_id else None
    if call.miss_reason is not None or employee is None:
        return Routed("missed", call.id, call.employee_id, reason=call.miss_reason)
    closed = await session.scalar(
        select(CallEvent.id)
        .where(CallEvent.call_id == call.id, CallEvent.type == "inbound_routed")
        .where(CallEvent.data["closed"].as_boolean().is_(True))
    )
    return Routed("answer", call.id, employee.id, employee.language, closed is not None)


async def _lead_for(
    session: AsyncSession, account_id: uuid.UUID, phone: str | None
) -> tuple[Lead | None, bool]:
    """The caller's lead, and whether they were already known. A new number becomes a lead."""
    if phone is None:
        return None, False
    lead = await session.scalar(
        select(Lead).where(Lead.account_id == account_id, Lead.phone == phone)
    )
    if lead is not None:
        return lead, True
    try:
        async with session.begin_nested():
            lead = Lead(account_id=account_id, phone=phone)
            session.add(lead)
            await session.flush()
    except IntegrityError:  # another call from the same number made it first
        lead = await session.scalar(
            select(Lead).where(Lead.account_id == account_id, Lead.phone == phone)
        )
        return lead, True
    return lead, False


async def _decide(
    session: AsyncSession, *, to: str, caller: str, carrier_id: str, now: datetime
) -> Routed:
    number = await session.scalar(
        select(PhoneNumber).where(PhoneNumber.e164 == to, PhoneNumber.status.in_(ANSWERABLE))
    )
    if number is None:
        return Routed("unknown")  # not one of ours: nothing to record
    employee = await session.scalar(select(Employee).where(Employee.number_id == number.id))
    settings = inbound_of(employee.inbound if employee else None)
    phone = caller_number(caller)
    lead, known = await _lead_for(session, number.account_id, normalize_phone(phone))
    call = Call(
        account_id=number.account_id,
        employee_id=employee.id if employee else None,
        lead_id=lead.id if lead else None,
        number_id=number.id,
        direction=Direction.INBOUND,
        channel=employee.channel if employee else Channel.INBOUND,
        status=CallStatus.RINGING,
        started_at=now,
        carrier_call_id=carrier_id,
        carrier_leg_id=carrier_id,  # an incoming call has one id, and the callbacks name it
        caller_phone=phone,
    )
    refusal = await _refusal(session, number, employee, settings, now)
    closed = False
    if refusal is None and not is_open(now, settings):
        if settings.closed_mode == "hang_up":
            refusal = ("closed", CLOSED)
        else:
            closed = True
    if refusal is None:
        # Last, because it takes the number's lock until the call row is saved.
        if not await channels.has_free_channel(session, number):
            refusal = ("busy", BUSY)
    session.add(call)
    await session.flush()
    if refusal is not None:
        code, reason = refusal
        call.status, call.ended_at = CallStatus.NO_ANSWER, now
        call.miss_reason, call.billing_status = reason, "free"  # nobody talked: nothing to bill
        session.add(
            CallEvent(call_id=call.id, type="missed", data={"code": code, "reason": reason})
        )
        if code == "credits":
            await _tell_owner(session, call, reason, now)
        if employee is not None:
            await callbacks.schedule_auto(session, call, employee, settings, code, now)
        return Routed("missed", call.id, call.employee_id, reason=reason, code=code)
    assert employee is not None  # a refusal covers a number without one
    session.add(
        CallEvent(
            call_id=call.id,
            type="inbound_routed",
            data={"closed": closed, "returning": known},
        )
    )
    return Routed("answer", call.id, employee.id, employee.language, closed)


async def _refusal(
    session: AsyncSession,
    number: PhoneNumber,
    employee: Employee | None,
    settings: InboundSettings,
    now: datetime,
) -> tuple[str, str] | None:
    """(code, reason in plain words) why this call is not answered, or None."""
    if employee is None:
        return "unattached", UNATTACHED
    if employee.status is not EmployeeStatus.LIVE:
        return "paused", NOT_LIVE
    if employee.channel is not Channel.INBOUND and not settings.answer_callbacks:
        return "no_callbacks", NO_CALLS
    held = await credit_policy.blocked_reason(session, number.account_id, now)
    if held is not None:
        return "credits", held
    tier = await failover.employee_tier(session, employee)
    down = await failover.blocked_reason(session, tier, now, outbound=False)
    if down is not None:
        return "unavailable", down
    verdict = await policy.check_dial(session, employee, number, "inbound")
    if not verdict.allowed:
        return "rule", verdict.reason
    return None


async def _tell_owner(session: AsyncSession, call: Call, reason: str, now: datetime) -> None:
    """A caller was turned away for want of credits: the owner hears of it (at most every 6 h)."""
    recent = await session.scalar(
        select(Notification.id).where(
            Notification.account_id == call.account_id,
            Notification.kind == "inbound_missed_credits",
            Notification.created_at > now - BLOCKED_NOTE_EVERY,
        )
    )
    if recent is None:
        session.add(
            Notification(
                account_id=call.account_id,
                kind="inbound_missed_credits",
                title="A caller could not be answered",
                created_at=now,
                body=f"Someone rang and nobody answered: {reason}. Top up so incoming calls "
                "are answered again.",
            )
        )
