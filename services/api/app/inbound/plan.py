"""What an incoming call (or the call back to a missed caller) adds to the employee's plan: the
opening, the closed and transfer rules, and what we already know about the caller."""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.employees.compiler import CallContext, clean_value
from app.employees.runtime import business_name
from app.inbound import greeting
from app.inbound.settings import of as inbound_of
from app.models import (
    Call,
    CallEvent,
    Campaign,
    CampaignContact,
    Channel,
    Direction,
    Employee,
    Lead,
    PhoneNumber,
)

CALLED_BACK = "They rang earlier and nobody could answer, so you are calling them back."


@dataclass(frozen=True)
class Extras:
    context: CallContext
    opening: str = ""
    transfer_to: str | None = None
    caller_id: str | None = None
    variables: dict[str, str] = field(default_factory=dict)  # a Bulk employee's own list row


async def extras(
    session: AsyncSession, employee: Employee, record: Call, lead: Lead | None
) -> Extras | None:
    """None for an ordinary call: nothing is added. A test call is not a caller's: it runs the
    script as written."""
    if record.is_test:
        return None
    if record.direction is not Direction.INBOUND:
        if record.callback_of_id is not None:
            return Extras(CallContext(notes=(CALLED_BACK,)))
        return None
    settings = inbound_of(employee.inbound)
    routed = (
        await session.scalar(
            select(CallEvent.data)
            .where(CallEvent.call_id == record.id, CallEvent.type == "inbound_routed")
            .order_by(CallEvent.id)
            .limit(1)
        )
        or {}
    )
    closed, returning = bool(routed.get("closed")), bool(routed.get("returning"))
    opening = greeting.opening(
        settings,
        employee.language,
        business_name=clean_value(await business_name(session, employee)),
        caller_name=clean_value(lead.name) if lead and lead.name else None,
        returning=returning,
        closed=closed,
    )
    notes: list[str] = []
    if returning and lead is not None:
        last = await session.scalar(
            select(Call.summary)
            .where(Call.lead_id == lead.id, Call.id != record.id, Call.summary.is_not(None))
            .order_by(Call.created_at.desc())
            .limit(1)
        )
        if last:
            notes.append(f"Their last call with you: {last}")
    contact = await _own_list_row(session, employee, lead)
    number = await session.get(PhoneNumber, record.number_id) if record.number_id else None
    person = settings.transfer_number if number is not None else None
    return Extras(
        CallContext(
            incoming=True,
            opening=opening,
            closed=closed,
            transfer_when=settings.transfer_when if person else None,
            notes=tuple(notes),
        ),
        opening=opening,
        transfer_to=person,
        caller_id=number.e164 if person and number else None,
        variables=dict(contact.variables) if contact else {},
    )


async def _own_list_row(
    session: AsyncSession, employee: Employee, lead: Lead | None
) -> CampaignContact | None:
    """A Bulk employee that is rung back knows the row of its own list the caller came from."""
    if lead is None or employee.channel is not Channel.BULK:
        return None
    return await session.scalar(
        select(CampaignContact)
        .join(Campaign, Campaign.id == CampaignContact.campaign_id)
        .where(Campaign.employee_id == employee.id, CampaignContact.phone == lead.phone)
        .order_by(CampaignContact.created_at.desc())
        .limit(1)
    )
