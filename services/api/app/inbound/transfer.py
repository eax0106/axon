"""Handing a live call to a person: who to ring, and what to do when nobody answers."""

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.inbound import messages
from app.inbound.settings import of as inbound_of
from app.models import Call, CallEvent, CallStatus, Direction, Employee, Lead, PhoneNumber

DIAL_TIMEOUT_S = 30  # how long the person's phone rings before we give up
DIAL_LIMIT_S = 3600  # the longest the bridged conversation may run


async def target(session: AsyncSession, call_id: uuid.UUID) -> tuple[str, str] | None:
    """(the person's number, the caller id to show: the employee's own number) for a call that is
    live and inbound, or None. Read from the employee's settings now, not carried in a URL."""
    call = await session.get(Call, call_id)
    if (
        call is None
        or call.direction is not Direction.INBOUND
        or call.status is not CallStatus.IN_PROGRESS
        or call.employee_id is None
    ):
        return None
    employee = await session.get(Employee, call.employee_id)
    number = await session.get(PhoneNumber, call.number_id) if call.number_id else None
    if employee is None or number is None:
        return None
    person = inbound_of(employee.inbound).transfer_number
    return (person, number.e164) if person else None


async def record_result(
    session: AsyncSession, call_id: uuid.UUID, dial_status: str, now: datetime
) -> None:
    """What the carrier says the transfer came to, and the end of the call: it stayed up (and kept
    its channel) while the person was rung. When the person did not pick up, the owner gets a
    message to follow up: the caller asked for a human and has not had one. Does not commit."""
    call = await session.get(Call, call_id, with_for_update=True)
    if call is None:
        return
    session.add(CallEvent(call_id=call.id, type="transfer_result", data={"status": dial_status}))
    if call.status is CallStatus.IN_PROGRESS:  # the call stayed up through the hand-over
        call.status, call.ended_at = CallStatus.COMPLETED, now
        if call.answered_at is not None:
            call.duration_s = max(0, round((now - call.answered_at).total_seconds()))
    if dial_status == "completed":
        return
    lead = await session.get(Lead, call.lead_id) if call.lead_id else None
    await messages.add(
        session,
        call,
        f"Asked to speak to a person, but the transfer did not connect ({dial_status}).",
        None,
        lead,
        now,
    )
