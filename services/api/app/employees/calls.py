"""Test an employee: a free phone call to the owner's phone, and a call from the browser."""

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, StringConstraints
from sqlalchemy import func, select

from app.auth import CurrentUser
from app.db import Session
from app.employees import tickets
from app.employees.router import load
from app.models import Call, CallStatus, Direction, Employee, PhoneNumber
from app.providers.base import ProviderKind, TelephonyProvider
from app.providers.registry import require
from app.settings import engine_public_url

router = APIRouter(prefix="/employees")

# Test calls cost nothing, so cap them: 5 an hour per employee, and Indian mobile numbers only.
TEST_CALLS_PER_HOUR = 5
INDIAN_MOBILE = re.compile(r"^\+91[6-9]\d{9}$")


class TestCallRequest(BaseModel):
    phone: Annotated[str, StringConstraints(pattern=INDIAN_MOBILE.pattern)]


async def _new_test_call(session: Session, employee: Employee, direction: Direction) -> Call:
    since = datetime.now(UTC) - timedelta(hours=1)
    recent = await session.scalar(
        select(func.count())
        .select_from(Call)
        .where(Call.employee_id == employee.id, Call.is_test.is_(True), Call.created_at > since)
    )
    if (recent or 0) >= TEST_CALLS_PER_HOUR:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, f"at most {TEST_CALLS_PER_HOUR} test calls an hour"
        )
    call = Call(
        account_id=employee.account_id,
        employee_id=employee.id,
        direction=direction,
        channel=employee.channel,
        status=CallStatus.QUEUED,
        is_test=True,
    )
    session.add(call)
    await session.flush()
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
    call = await _new_test_call(session, employee, Direction.OUTBOUND)
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
    call = await _new_test_call(session, employee, Direction.INBOUND)
    await session.commit()
    ticket = tickets.issue(
        tickets.WebTicket(employee_id=employee.id, call_id=call.id, account_id=employee.account_id)
    )
    return {
        "call_id": str(call.id),
        "ticket": ticket,
        "ws_url": "wss://" + base.removeprefix("https://") + f"/web/stream?ticket={ticket}",
        "expires_in": int(tickets.TTL.total_seconds()),
    }
