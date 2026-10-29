"""Owner-facing endpoints for an Instant employee: intake URL and secret, dialer rules, intake log,
queue console, redial and one-off calls, and the Meta and Sheets connections."""

import secrets
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, not_impersonating
from app.db import Session
from app.employees import tickets
from app.employees.router import OwnerUser, load
from app.instant import intake, rules
from app.instant.public import SECRET_HEADER
from app.instant.rules import DialerSettings
from app.models import (
    Call,
    CallStatus,
    Channel,
    DncEntry,
    Employee,
    EmployeeStatus,
    IntakeStatus,
    Lead,
    LeadConnection,
    LeadIntakeEntry,
)
from app.providers.base import ProviderKind, SheetsProvider
from app.providers.google import sheets as google_sheets
from app.providers.leads.meta_lead_ads import MetaLeadAds
from app.providers.registry import require

router = APIRouter()
ACTIVE = (CallStatus.QUEUED, CallStatus.RINGING, CallStatus.IN_PROGRESS)


async def instant_employee(session: AsyncSession, user: Any, employee_id: uuid.UUID) -> Employee:
    employee = await load(session, user, employee_id)
    if employee.channel is not Channel.INSTANT:
        raise HTTPException(status.HTTP_409_CONFLICT, "this employee is not on the Instant channel")
    return employee


async def connection_of(session: AsyncSession, employee: Employee) -> LeadConnection:
    """The employee's lead connection, created with its first secret on first use."""
    found = await session.scalar(
        select(LeadConnection).where(LeadConnection.employee_id == employee.id)
    )
    if found is None:
        found = LeadConnection(
            account_id=employee.account_id,
            employee_id=employee.id,
            secret=secrets.token_urlsafe(32),
        )
        session.add(found)
        await session.commit()
    return found


@router.get("/employees/{employee_id}/instant")
async def overview(employee_id: uuid.UUID, user: CurrentUser, session: Session) -> dict[str, Any]:
    employee = await instant_employee(session, user, employee_id)
    connection = await connection_of(session, employee)
    return {
        "intake_path": f"/lead-intake/{connection.id}",
        "secret_header": SECRET_HEADER,
        "dialer": DialerSettings.model_validate(employee.dialer or {}).model_dump(),
        "meta": {"form_id": connection.meta_form_id, "token_set": bool(connection.meta_page_token)},
        "sheets": {
            "sheet_id": connection.sheet_id,
            "range": connection.sheet_range,
            "connected": bool(connection.google_refresh_token),
        },
    }


@router.post(
    "/employees/{employee_id}/instant/secret/reveal", dependencies=[Depends(not_impersonating)]
)
async def reveal_secret(
    employee_id: uuid.UUID, user: OwnerUser, session: Session
) -> dict[str, str]:
    employee = await instant_employee(session, user, employee_id)
    return {"secret": (await connection_of(session, employee)).secret}


@router.post(
    "/employees/{employee_id}/instant/secret/rotate", dependencies=[Depends(not_impersonating)]
)
async def rotate_secret(
    employee_id: uuid.UUID, user: OwnerUser, session: Session
) -> dict[str, str]:
    """A new secret; the old one stops working at once."""
    employee = await instant_employee(session, user, employee_id)
    connection = await connection_of(session, employee)
    connection.secret = secrets.token_urlsafe(32)
    connection.rotated_at = datetime.now(UTC)
    await session.commit()
    return {"secret": connection.secret}


@router.get("/employees/{employee_id}/instant/dialer")
async def get_dialer(employee_id: uuid.UUID, user: CurrentUser, session: Session) -> DialerSettings:
    employee = await instant_employee(session, user, employee_id)
    return DialerSettings.model_validate(employee.dialer or {})


@router.put("/employees/{employee_id}/instant/dialer")
async def put_dialer(
    employee_id: uuid.UUID, body: DialerSettings, user: CurrentUser, session: Session
) -> DialerSettings:
    employee = await instant_employee(session, user, employee_id)
    employee.dialer = body.model_dump()
    await session.commit()
    return body


class IntakeOut(BaseModel):
    id: int
    at: datetime
    source: str
    status: IntakeStatus
    reason: str | None
    phone: str | None
    lead_id: uuid.UUID | None
    call_id: uuid.UUID | None


@router.get("/employees/{employee_id}/instant/intake-log")
async def intake_log(
    employee_id: uuid.UUID,
    user: CurrentUser,
    session: Session,
    outcome: IntakeStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[IntakeOut]:
    employee = await instant_employee(session, user, employee_id)
    query = (
        select(LeadIntakeEntry)
        .where(LeadIntakeEntry.employee_id == employee.id)
        .order_by(LeadIntakeEntry.id.desc())
        .limit(limit)
    )
    if outcome:
        query = query.where(LeadIntakeEntry.status == outcome)
    return [
        IntakeOut(
            id=e.id,
            at=e.created_at,
            source=e.source,
            status=e.status,
            reason=e.reason,
            phone=e.phone,
            lead_id=e.lead_id,
            call_id=e.call_id,
        )
        for e in await session.scalars(query)
    ]


class LeadIn(BaseModel):
    phone: str = Field(max_length=40)
    name: str | None = Field(default=None, max_length=200)
    fields: dict[str, str] = Field(default_factory=dict, max_length=50)


def _payload(body: LeadIn) -> dict[str, Any]:
    return {**body.fields, "phone": body.phone, **({"name": body.name} if body.name else {})}


def _outcome(result: intake.Result) -> dict[str, Any]:
    return {
        "status": result.status,
        "reason": result.reason,
        "lead_id": result.lead_id,
        "call_id": result.call_id,
        "scheduled_for": result.scheduled_for,
        "variables": result.variables,
    }


@router.post("/employees/{employee_id}/instant/test-lead")
async def test_lead(
    employee_id: uuid.UUID, body: LeadIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    """Run a lead through every rule and the log without making a lead or a call."""
    employee = await instant_employee(session, user, employee_id)
    result = await intake.process(
        session, employee, _payload(body), source="test", now=datetime.now(UTC), dry_run=True
    )
    return _outcome(result)


@router.post("/employees/{employee_id}/instant/call", status_code=status.HTTP_202_ACCEPTED)
async def one_off_call(
    employee_id: uuid.UUID, body: LeadIn, user: CurrentUser, session: Session
) -> dict[str, Any]:
    """Call any number now (inside the calling window and off the do-not-call list)."""
    employee = await instant_employee(session, user, employee_id)
    result = await intake.process(
        session, employee, _payload(body), source="manual", now=datetime.now(UTC), dedupe=False
    )
    if result.status is IntakeStatus.REJECTED:
        raise HTTPException(422, result.reason)
    return _outcome(result)


class QueueItem(BaseModel):
    call_id: uuid.UUID
    phone: str | None
    name: str | None
    attempt: int
    status: CallStatus
    state: str  # waiting, held, ringing, in_progress, or the final status
    scheduled_for: datetime | None
    ended_at: datetime | None


def _state(call: Call) -> str:
    if call.status is CallStatus.QUEUED:
        return "held" if call.scheduled_for is None else "waiting"
    return call.status.value


@router.get("/employees/{employee_id}/instant/queue")
async def queue(
    employee_id: uuid.UUID,
    user: CurrentUser,
    session: Session,
    recent: Annotated[int, Query(ge=0, le=100)] = 20,
) -> dict[str, list[QueueItem]]:
    """Calls waiting, held and under way, then the most recent finished ones."""
    employee = await instant_employee(session, user, employee_id)

    async def items(*where: Any, limit: int | None, newest_first: bool = False) -> list[QueueItem]:
        order = Call.created_at.desc() if newest_first else Call.scheduled_for.asc().nulls_first()
        query = (
            select(Call, Lead)
            .join(Lead, Lead.id == Call.lead_id, isouter=True)
            .where(Call.employee_id == employee.id, Call.is_test.is_(False), *where)
            .order_by(order)
        )
        if limit is not None:
            query = query.limit(limit)
        rows = (await session.execute(query)).all()
        return [
            QueueItem(
                call_id=c.id,
                phone=lead.phone if lead else None,
                name=lead.name if lead else None,
                attempt=c.attempt,
                status=c.status,
                state=_state(c),
                scheduled_for=c.scheduled_for,
                ended_at=c.ended_at,
            )
            for c, lead in rows
        ]

    return {
        "active": await items(Call.status.in_(ACTIVE), limit=None),
        "recent": await items(Call.status.not_in(ACTIVE), limit=recent, newest_first=True),
    }


async def _own_call(session: AsyncSession, employee: Employee, call_id: uuid.UUID) -> Call:
    call = await session.scalar(
        select(Call).where(
            Call.id == call_id, Call.employee_id == employee.id, Call.is_test.is_(False)
        )
    )
    if call is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "call not found")
    return call


@router.post("/employees/{employee_id}/instant/queue/{call_id}/cancel")
async def cancel(
    employee_id: uuid.UUID, call_id: uuid.UUID, user: CurrentUser, session: Session
) -> dict[str, Any]:
    employee = await instant_employee(session, user, employee_id)
    call = await _own_call(session, employee, call_id)
    if call.status is not CallStatus.QUEUED:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "only a waiting or held call can be cancelled"
        )
    call.status = CallStatus.CANCELED
    await session.commit()
    return {"call_id": call.id, "status": call.status}


@router.post(
    "/employees/{employee_id}/instant/queue/{call_id}/redial", status_code=status.HTTP_202_ACCEPTED
)
async def redial(
    employee_id: uuid.UUID, call_id: uuid.UUID, user: CurrentUser, session: Session
) -> dict[str, Any]:
    """Try the lead again from attempt 1: a held call is released, a finished one is re-queued.
    The calling window and the do-not-call list still apply."""
    employee = await instant_employee(session, user, employee_id)
    call = await _own_call(session, employee, call_id)
    if call.status in (CallStatus.RINGING, CallStatus.IN_PROGRESS):
        raise HTTPException(status.HTTP_409_CONFLICT, "that call is under way")
    if employee.status is not EmployeeStatus.LIVE:
        raise HTTPException(status.HTTP_409_CONFLICT, "employee is not live")
    lead = await session.get(Lead, call.lead_id) if call.lead_id else None
    if lead is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "the lead no longer exists")
    on_dnc = await session.scalar(
        select(DncEntry.id).where(
            DncEntry.account_id == call.account_id, DncEntry.phone == lead.phone
        )
    )
    if on_dnc:
        raise HTTPException(status.HTTP_409_CONFLICT, "number is on the do-not-call list")
    settings = DialerSettings.model_validate(employee.dialer or {})
    when = rules.next_window_start(datetime.now(UTC), settings, rules.IST)
    if call.status is CallStatus.QUEUED:
        call.scheduled_for = when  # releases a held call, or brings a waiting one forward
        target = call
    elif waiting := await session.scalar(
        select(Call).where(
            Call.employee_id == employee.id,
            Call.lead_id == lead.id,
            Call.status == CallStatus.QUEUED,
        )
    ):
        waiting.scheduled_for = when  # a double click does not queue the lead twice
        target = waiting
    else:
        target = Call(
            account_id=call.account_id,
            employee_id=employee.id,
            lead_id=lead.id,
            direction=call.direction,
            channel=call.channel,
            status=CallStatus.QUEUED,
            scheduled_for=when,
            attempt=1,
        )
        session.add(target)
    await session.commit()
    return {"call_id": target.id, "scheduled_for": when}


class MetaBody(BaseModel):
    form_id: str = Field(min_length=1, max_length=50)
    page_access_token: str = Field(min_length=1, max_length=2000)


@router.put("/employees/{employee_id}/instant/meta", dependencies=[Depends(not_impersonating)])
async def connect_meta(
    employee_id: uuid.UUID, body: MetaBody, user: OwnerUser, session: Session
) -> dict[str, str]:
    """Send this lead form's leads to the employee. The page token is how we read each lead."""
    employee = await instant_employee(session, user, employee_id)
    connection = await connection_of(session, employee)
    if not await meta_provider().can_read_form(body.form_id, body.page_access_token):
        raise HTTPException(422, "that token cannot read that lead form")
    taken = await session.scalar(
        select(LeadConnection.id).where(
            LeadConnection.meta_form_id == body.form_id, LeadConnection.id != connection.id
        )
    )
    if taken:
        raise HTTPException(status.HTTP_409_CONFLICT, "that form is already connected")
    connection.meta_form_id, connection.meta_page_token = body.form_id, body.page_access_token
    await session.commit()
    return {"form_id": body.form_id}


def meta_provider() -> MetaLeadAds:
    provider = require(ProviderKind.LEADS)
    assert isinstance(provider, MetaLeadAds)
    return provider


def sheets_provider() -> SheetsProvider:
    provider = require(ProviderKind.SHEETS)
    assert isinstance(provider, SheetsProvider)
    return provider


@router.get("/employees/{employee_id}/instant/sheets/consent-url")
async def sheets_consent_url(
    employee_id: uuid.UUID,
    redirect_uri: Annotated[str, Query(min_length=8, max_length=500)],
    user: OwnerUser,
    session: Session,
) -> dict[str, str]:
    employee = await instant_employee(session, user, employee_id)
    sheets_provider()  # 503 until the Google OAuth client is configured
    state = tickets.issue_oauth_state(user.id, employee.id)
    return {"url": google_sheets.consent_url(redirect_uri, state=state)}


class SheetsConnect(BaseModel):
    code: str = Field(min_length=1, max_length=2000)
    state: str = Field(min_length=1, max_length=2000)
    redirect_uri: str = Field(min_length=8, max_length=500)


@router.post(
    "/employees/{employee_id}/instant/sheets/connect", dependencies=[Depends(not_impersonating)]
)
async def sheets_connect(
    employee_id: uuid.UUID, body: SheetsConnect, user: OwnerUser, session: Session
) -> dict[str, bool]:
    employee = await instant_employee(session, user, employee_id)
    if tickets.read_oauth_state(body.state) != (user.id, employee.id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "bad or expired state: start the connection again"
        )
    refresh = await sheets_provider().exchange_code(body.code, body.redirect_uri)
    connection = await connection_of(session, employee)
    connection.google_refresh_token = refresh
    await session.commit()
    return {"connected": True}


class SheetBody(BaseModel):
    sheet_id: str = Field(min_length=1, max_length=100)
    range: str = Field(default="A:Z", min_length=1, max_length=100)


@router.put("/employees/{employee_id}/instant/sheets", dependencies=[Depends(not_impersonating)])
async def sheets_choose(
    employee_id: uuid.UUID, body: SheetBody, user: OwnerUser, session: Session
) -> dict[str, Any]:
    """Pick the sheet. Rows already in it are not called: only rows added from now on are."""
    employee = await instant_employee(session, user, employee_id)
    connection = await connection_of(session, employee)
    if not connection.google_refresh_token:
        raise HTTPException(status.HTTP_409_CONFLICT, "connect Google first")
    rows = await sheets_provider().read_rows(
        connection.google_refresh_token, body.sheet_id, body.range
    )
    connection.sheet_id, connection.sheet_range = body.sheet_id, body.range
    connection.sheet_cursor = len(rows)
    await session.commit()
    return {"sheet_id": body.sheet_id, "rows_skipped": len(rows)}
