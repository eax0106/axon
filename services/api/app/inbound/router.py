"""Incoming calls, as the dashboard sees them: the settings, the messages and call-back requests
callers leave, and the callers nobody answered. All scoped to the caller's account."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, refuse_in_support_session
from app.db import Session
from app.employees.router import OwnerUser, load
from app.inbound import connect
from app.inbound.settings import InboundSettings
from app.inbound.settings import of as inbound_of
from app.models import (
    Call,
    CallEvent,
    CallStatus,
    Employee,
    InboundMessage,
    Lead,
    PhoneNumber,
)

router = APIRouter()

CALLBACK_STATES = {
    CallStatus.QUEUED: "scheduled",
    CallStatus.RINGING: "calling",
    CallStatus.IN_PROGRESS: "calling",
    CallStatus.COMPLETED: "answered",
    CallStatus.NO_ANSWER: "not_answered",
    CallStatus.BUSY: "not_answered",
    CallStatus.FAILED: "not_answered",
    CallStatus.CANCELED: "cancelled",
}


@router.get("/employees/{employee_id}/inbound-settings")
async def get_settings(
    employee_id: uuid.UUID, user: CurrentUser, session: Session
) -> InboundSettings:
    return inbound_of((await load(session, user, employee_id)).inbound)


@router.put("/employees/{employee_id}/inbound-settings")
async def put_settings(
    employee_id: uuid.UUID,
    body: InboundSettings,
    request: Request,
    user: OwnerUser,
    session: Session,
) -> InboundSettings:
    """Applies to the next call at once. The transfer number may not be the employee's own number:
    the call would ring itself. A support session may not change it: callers would be put through
    to a phone of its choosing after it ends."""
    employee = await load(session, user, employee_id)
    if body.transfer_number != inbound_of(employee.inbound).transfer_number:
        refuse_in_support_session(request)
    number = await session.get(PhoneNumber, employee.number_id) if employee.number_id else None
    if number is not None and body.transfer_number == number.e164:
        raise HTTPException(422, "the transfer number cannot be the employee's own number")
    employee.inbound = body.model_dump()
    await session.commit()
    return body


@router.post("/employees/{employee_id}/inbound/connect")
async def connect_number(
    employee_id: uuid.UUID, user: OwnerUser, session: Session
) -> dict[str, Any]:
    """Send incoming calls on the employee's number to us (done at go-live; this repeats it, for
    instance after the carrier keys were added). 503 until the keys and public URLs exist."""
    employee = await load(session, user, employee_id)
    number = await connect.connect(session, employee)
    await session.commit()
    return {"connected": True, "number": number.e164}


# --- Messages ----------------------------------------------------------------------------------


def _message(m: InboundMessage, employee_name: str | None) -> dict[str, Any]:
    return {
        "id": m.id,
        "call_id": m.call_id,
        "employee_id": m.employee_id,
        "employee_name": employee_name,
        "lead_id": m.lead_id,
        "phone": m.phone,
        "name": m.name,
        "body": m.body,
        "callback_at": m.callback_at,
        "done": m.done_at is not None,
        "done_at": m.done_at,
        "created_at": m.created_at,
    }


@router.get("/inbound/messages")
async def list_messages(
    user: CurrentUser,
    session: Session,
    state: Literal["open", "done", "all"] = "open",
    employee_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    query: Any = (
        select(InboundMessage, Employee.name)
        .join(Employee, Employee.id == InboundMessage.employee_id, isouter=True)
        .where(InboundMessage.account_id == user.account_id)
    )
    if state != "all":
        done = InboundMessage.done_at.is_not(None)
        query = query.where(done if state == "done" else ~done)
    if employee_id is not None:
        query = query.where(InboundMessage.employee_id == employee_id)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await session.execute(
            query.order_by(InboundMessage.created_at.desc(), InboundMessage.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return {"total": total or 0, "items": [_message(m, name) for m, name in rows]}


async def _tick(
    session: AsyncSession, user: CurrentUser, message_id: uuid.UUID, *, done: bool
) -> dict[str, Any]:
    message = await session.scalar(
        select(InboundMessage).where(
            InboundMessage.id == message_id, InboundMessage.account_id == user.account_id
        )
    )
    if message is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "message not found")
    message.done_at = datetime.now(UTC) if done else None
    message.done_by = user.id if done else None
    await session.commit()
    employee = await session.get(Employee, message.employee_id) if message.employee_id else None
    return _message(message, employee.name if employee else None)


@router.post("/inbound/messages/{message_id}/done")
async def mark_done(message_id: uuid.UUID, user: CurrentUser, session: Session) -> dict[str, Any]:
    return await _tick(session, user, message_id, done=True)


@router.post("/inbound/messages/{message_id}/reopen")
async def reopen(message_id: uuid.UUID, user: CurrentUser, session: Session) -> dict[str, Any]:
    return await _tick(session, user, message_id, done=False)


# --- Missed callers ----------------------------------------------------------------------------


@router.get("/inbound/missed")
async def list_missed(
    user: CurrentUser,
    session: Session,
    employee_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    """Callers nobody answered, newest first, with why, and what became of the auto call-back."""
    where = [Call.account_id == user.account_id, Call.miss_reason.is_not(None)]
    if employee_id is not None:
        where.append(Call.employee_id == employee_id)
    total = await session.scalar(select(func.count()).where(*where))
    rows = (
        await session.execute(
            select(Call, Employee.name, Lead.phone, Lead.name)
            .join(Employee, Employee.id == Call.employee_id, isouter=True)
            .join(Lead, Lead.id == Call.lead_id, isouter=True)
            .where(*where)
            .order_by(Call.created_at.desc(), Call.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    ids = [r[0].id for r in rows]
    callbacks = {
        c.callback_of_id: c
        for c in await session.scalars(select(Call).where(Call.callback_of_id.in_(ids)))
    }
    events = (
        await session.execute(
            select(CallEvent.call_id, CallEvent.type, CallEvent.data)
            .where(
                CallEvent.call_id.in_(ids),
                CallEvent.type.in_(("missed", "auto_callback_skipped")),
            )
            .order_by(CallEvent.id)
        )
    ).all()
    code: dict[uuid.UUID, str] = {}
    skipped: dict[uuid.UUID, str] = {}
    for call_id, kind, data in events:
        if kind == "missed":
            code[call_id] = str(data.get("code", ""))
        else:
            skipped[call_id] = str(data.get("reason", ""))
    items = []
    for call, employee_name, phone, name in rows:
        back = callbacks.get(call.id)
        items.append(
            {
                "call_id": call.id,
                "at": call.created_at,
                "employee_id": call.employee_id,
                "employee_name": employee_name,
                "phone": phone or call.caller_phone,
                "name": name,
                "reason": call.miss_reason,
                "code": code.get(call.id),
                "auto_callback": {
                    "state": CALLBACK_STATES[back.status] if back else "none",
                    "at": back.scheduled_for if back else None,
                    "call_id": back.id if back else None,
                    "not_made_because": None if back else skipped.get(call.id),
                },
            }
        )
    return {"total": total or 0, "items": items}
