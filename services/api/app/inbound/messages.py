"""Messages and call-back requests a caller leaves: tasks for the owner, with a done tick."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Call, InboundMessage, Lead, Notification

MAX_BODY = 2000


async def add(
    session: AsyncSession,
    call: Call,
    body: str,
    callback_at: datetime | None,
    lead: Lead | None,
    now: datetime,
) -> InboundMessage:
    """The call's message, made or added to (a call has one, whatever the order its parts arrive
    in). The owner gets a bell entry when it is made. Does not commit."""
    existing = await session.scalar(select(InboundMessage).where(InboundMessage.call_id == call.id))
    if existing is not None:
        if body not in existing.body:
            existing.body = f"{existing.body}\n{body}"[:MAX_BODY]
        existing.callback_at = existing.callback_at or callback_at
        return existing
    who = (lead.name if lead else None) or (lead.phone if lead else None) or call.caller_phone
    message = InboundMessage(
        account_id=call.account_id,
        employee_id=call.employee_id,
        call_id=call.id,
        lead_id=call.lead_id,
        phone=(lead.phone if lead else None) or call.caller_phone,
        name=lead.name if lead else None,
        body=body[:MAX_BODY],
        callback_at=callback_at,
        created_at=now,
    )
    session.add(message)
    session.add(
        Notification(
            account_id=call.account_id,
            kind="inbound_message",
            title=f"New message from {who or 'a caller'}",
            body=body[:300],
            created_at=now,
        )
    )
    return message
