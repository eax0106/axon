"""Test an employee: a free phone call to the owner's phone, and a call from the browser."""

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, StringConstraints

from app.auth import CurrentUser
from app.db import Session
from app.employees import tickets
from app.employees.limits import TEST_CALLS_PER_HOUR, take
from app.employees.router import load
from app.models import Call, CallStatus, Direction, Employee, PhoneNumber, User
from app.providers.base import ProviderKind, TelephonyProvider
from app.providers.registry import require
from app.settings import engine_public_url

router = APIRouter(prefix="/employees")

# Test calls cost us vendor money but nothing is charged, so: Indian mobile numbers only, and
# a per-account hourly cap (not per employee: employees are free to create).
INDIAN_MOBILE = re.compile(r"^\+91[6-9]\d{9}$")


class TestCallRequest(BaseModel):
    phone: Annotated[str, StringConstraints(pattern=INDIAN_MOBILE.pattern)]


async def _new_test_call(
    session: Session, user: User, employee: Employee, direction: Direction
) -> Call:
    """Count the use against the account, then create the free call row (committed, so the
    account lock is released before any vendor call)."""
    await take(session, user, "test_call", TEST_CALLS_PER_HOUR)
    call = Call(
        account_id=employee.account_id,
        employee_id=employee.id,
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
    employee_id: uuid.UUID, body: TestCallRequest, user: CurrentUser, session: Session
) -> dict[str, str]:
    """Ring `phone` and let the employee talk on its draft script. Free; not in any stats."""
    employee = await load(session, user, employee_id)
    number = await session.get(PhoneNumber, employee.number_id) if employee.number_id else None
    if number is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "attach a phone number to place test calls")
    telephony = require(ProviderKind.TELEPHONY)
    assert isinstance(telephony, TelephonyProvider)
    base = engine_public_url()
    call = await _new_test_call(session, user, employee, Direction.OUTBOUND)
    answer_url = f"{base}/vobiz/answer?employee={employee.id}&call={call.id}"
    try:
        carrier_id = await telephony.originate(number.e164, body.phone, answer_url)
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
