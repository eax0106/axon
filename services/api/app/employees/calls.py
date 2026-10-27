"""Test an employee: a free call to the owner's verified phone, and a call from the browser."""

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, StringConstraints
from sqlalchemy import select

from app.auth import CurrentUser
from app.db import Session
from app.employees import tickets
from app.employees.limits import TEST_CALLS_PER_HOUR, take
from app.employees.router import load
from app.instant.policy import check_dial
from app.models import Account, Call, CallStatus, Direction, DncEntry, Employee, PhoneNumber, User
from app.numbers import channels
from app.providers.base import ProviderKind, TelephonyProvider
from app.providers.registry import require
from app.settings import engine_public_url

router = APIRouter(prefix="/employees")

# Test calls cost us vendor money but nothing is charged, so: only the owner's own phone (proved
# with a one-time code, app.phone_verify), through the do-not-call list and the dial rule table
# like any call, and a per-account hourly cap (not per employee: employees are free to create).
INDIAN_MOBILE = re.compile(r"^\+91[6-9]\d{9}$")


class TestCallRequest(BaseModel):
    phone: Annotated[str, StringConstraints(pattern=INDIAN_MOBILE.pattern)] | None = None


async def _new_test_call(
    session: Session,
    user: User,
    employee: Employee,
    direction: Direction,
    number: PhoneNumber | None = None,
) -> Call:
    """Count the use against the account, then create the free call row (committed, so the
    account lock is released before any vendor call). A call on a phone line carries the number,
    so once answered it holds one of the number's channels like any other call."""
    await take(session, user, "test_call", TEST_CALLS_PER_HOUR)
    call = Call(
        account_id=employee.account_id,
        employee_id=employee.id,
        number_id=number.id if number else None,
        direction=direction,
        channel=employee.channel,
        status=CallStatus.QUEUED,
        is_test=True,
    )
    session.add(call)
    await session.commit()
    return call


@router.post("/{employee_id}/test-call", status_code=status.HTTP_202_ACCEPTED)
async def test_call(
    employee_id: uuid.UUID, user: CurrentUser, session: Session, body: TestCallRequest | None = None
) -> dict[str, str]:
    """Ring the owner's verified phone and let the employee talk on its draft script. Free; not in
    any stats."""
    employee = await load(session, user, employee_id)
    number = await session.get(PhoneNumber, employee.number_id) if employee.number_id else None
    if number is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "attach a phone number to place test calls")
    account = await session.get(Account, user.account_id)
    assert account is not None  # FK guarantees it
    if account.owner_phone is None or account.owner_phone_verified_at is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "verify your phone with a one-time code before test calls"
        )
    phone = (body.phone if body else None) or account.owner_phone
    if phone != account.owner_phone:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "free test calls only ring your own verified phone"
        )
    on_dnc = await session.scalar(
        select(DncEntry.id).where(DncEntry.account_id == user.account_id, DncEntry.phone == phone)
    )
    if on_dnc:
        raise HTTPException(status.HTTP_409_CONFLICT, "that number is on the do-not-call list")
    verdict = await check_dial(session, employee, number, "outbound")
    if not verdict.allowed:
        raise HTTPException(status.HTTP_409_CONFLICT, verdict.reason)
    if not await channels.has_free_channel(session, number):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "every channel of the number is on a call: try again in a moment",
        )
    telephony = require(ProviderKind.TELEPHONY)
    assert isinstance(telephony, TelephonyProvider)
    base = engine_public_url()
    call = await _new_test_call(session, user, employee, Direction.OUTBOUND, number)
    answer_url = f"{base}/vobiz/answer?employee={employee.id}&call={call.id}"
    try:
        carrier_id = await telephony.originate(number.e164, phone, answer_url)
    except Exception:
        call.status = CallStatus.FAILED
        await session.commit()
        raise
    await session.commit()
    return {"call_id": str(call.id), "carrier_call_id": carrier_id}


@router.post("/{employee_id}/web-test-call", status_code=status.HTTP_201_CREATED)
async def web_test_call(
    employee_id: uuid.UUID, user: CurrentUser, session: Session
) -> dict[str, str | int]:
    """A ticket and WebSocket URL for talking to the draft from the browser. Free."""
    employee = await load(session, user, employee_id)
    base = engine_public_url()
    call = await _new_test_call(session, user, employee, Direction.INBOUND)
    ticket = tickets.issue(
        tickets.WebTicket(employee_id=employee.id, call_id=call.id, account_id=employee.account_id)
    )
    return {
        "call_id": str(call.id),
        "ticket": ticket,
        "ws_url": "wss://" + base.removeprefix("https://") + f"/web/stream?ticket={ticket}",
        "expires_in": int(tickets.TTL.total_seconds()),
    }
