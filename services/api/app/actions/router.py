"""Actions endpoints: the account's Google connection, an employee's actions, the test console."""

import logging
import uuid
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.actions import booking, service
from app.actions.schema import (
    ActionConfig,
    CalendarBooking,
    WhatsApp,
    mask,
)
from app.actions.tools import ActionContext, build_tools
from app.auth import CurrentUser
from app.db import Session
from app.employees import service as employees
from app.employees import tickets
from app.employees.limits import take
from app.employees.router import OwnerUser, load
from app.employees.script import ScriptBundle
from app.models import Account, GoogleConnection
from app.providers.base import CalendarProvider, ProviderKind
from app.providers.google import oauth
from app.providers.registry import require

log = logging.getLogger("axon.actions")
router = APIRouter()
TESTS_PER_HOUR = 30


def calendar_provider() -> CalendarProvider:
    provider = require(ProviderKind.CALENDAR)  # 503 until the Google OAuth client is configured
    assert isinstance(provider, CalendarProvider)
    return provider


@router.get("/integrations/google")
async def google_status(user: CurrentUser, session: Session) -> dict[str, bool]:
    connection = await session.get(GoogleConnection, user.account_id)
    return {"connected": connection is not None, **service.services_of(connection)}


@router.get("/integrations/google/consent-url")
async def google_consent_url(
    redirect_uri: Annotated[str, Query(min_length=8, max_length=500)],
    user: OwnerUser,
    services: Annotated[list[str], Query(min_length=1)],
) -> dict[str, str]:
    unknown = [s for s in services if s not in service.SERVICE_SCOPES]
    if unknown:
        raise HTTPException(422, f"unknown service {unknown[0]!r}: use calendar or sheets")
    calendar_provider()
    scope = " ".join(sorted({s for name in services for s in service.SERVICE_SCOPES[name]}))
    state = tickets.issue_oauth_state(user.id, user.account_id, purpose="google")
    return {"url": oauth.consent_url(redirect_uri, state, scope)}


class GoogleConnect(BaseModel):
    code: str = Field(min_length=1, max_length=2000)
    state: str = Field(min_length=1, max_length=2000)
    redirect_uri: str = Field(min_length=8, max_length=500)


@router.post("/integrations/google/connect")
async def google_connect(body: GoogleConnect, user: OwnerUser, session: Session) -> dict[str, bool]:
    if tickets.read_oauth_state(body.state, "google") != (user.id, user.account_id):
        raise HTTPException(400, "bad or expired state: start the connection again")
    grant = await calendar_provider().exchange_code(body.code, body.redirect_uri)
    account_id = user.account_id
    connection = GoogleConnection(
        account_id=account_id, refresh_token=grant.refresh_token, scopes=sorted(grant.scopes)
    )
    have = service.services_of(connection)
    if not any(have.values()):
        raise HTTPException(400, "Google was not allowed to use Calendar or Sheets")
    await session.merge(connection)
    await session.commit()
    return {"connected": True, **have}


@router.delete("/integrations/google", status_code=status.HTTP_204_NO_CONTENT)
async def google_disconnect(user: OwnerUser, session: Session) -> None:
    """Take the permission back at Google, then forget it. Actions that need it stop working."""
    connection = await session.get(GoogleConnection, user.account_id)
    if connection is None:
        return
    try:
        await calendar_provider().revoke(connection.refresh_token)
    except Exception as exc:  # the permission is forgotten here either way; Google may be down
        log.warning("google revoke failed: %s", type(exc).__name__)
    await session.execute(
        delete(GoogleConnection).where(GoogleConnection.account_id == user.account_id)
    )
    await session.commit()


class ActionsBody(BaseModel):
    actions: list[ActionConfig]


@router.get("/employees/{employee_id}/actions")
async def get_actions(employee_id: uuid.UUID, user: CurrentUser, session: Session) -> ActionsBody:
    employee = await load(session, user, employee_id)
    return ActionsBody(actions=mask(employees.bundle_of(employee).actions))


@router.put("/employees/{employee_id}/actions")
async def put_actions(
    employee_id: uuid.UUID, body: ActionsBody, user: CurrentUser, session: Session
) -> ActionsBody:
    """Replace the draft actions. They reach live calls only after publish, like the script."""
    employee = await load(session, user, employee_id)
    kept = await service.accept(
        session, user, list(body.actions), employees.bundle_of(employee).actions
    )
    try:
        bundle = employees.bundle_of(employee).model_copy(update={"actions": kept})
        employee.draft = ScriptBundle.model_validate(bundle.model_dump()).model_dump()
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_url=False, include_context=False)) from exc
    await session.commit()
    return ActionsBody(actions=mask(kept))


class TestBody(BaseModel):
    args: dict[str, Any] = Field(default_factory=dict)


@router.post("/employees/{employee_id}/actions/{name}/test")
async def test_action(
    employee_id: uuid.UUID,
    name: str,
    body: TestBody,
    request: Request,
    user: CurrentUser,
    session: Session,
) -> dict[str, Any]:
    """Run one of the draft's actions for real, as the test console: an HTTP call, a sheet read or
    write, a test booking (made and removed again), or a WhatsApp message to the owner's own
    verified phone."""
    employee = await load(session, user, employee_id)
    actions = [a for a in employees.bundle_of(employee).actions if a.name == name]
    if not actions:
        raise HTTPException(404, "no such action on this employee")
    action = actions[0]
    account = await session.get(Account, user.account_id)
    assert account is not None
    phone = account.owner_phone if account.owner_phone_verified_at else None
    if isinstance(action, WhatsApp) and phone is None:
        raise HTTPException(409, "verify your own phone first: the test message goes only there")
    lacking = await service.missing(session, user.account_id, [action])
    if lacking:
        raise HTTPException(409, f"connect Google {lacking[0]} first")
    await take(session, user, "action.test", TESTS_PER_HOUR)
    factory = async_sessionmaker(request.app.state.db, expire_on_commit=False)
    ctx = ActionContext(factory, user.account_id, None, phone, None)
    try:
        if isinstance(action, CalendarBooking):
            connection = await session.get(GoogleConnection, user.account_id)
            assert connection is not None  # service.missing() above proved it
            result = await booking.test_booking(
                action, calendar_provider(), connection.refresh_token, booking.now()
            )
        else:
            tool = build_tools([action], ctx, guarded=False)[0]
            result = await tool.run(body.args)
    except (httpx.HTTPError, RuntimeError) as exc:  # a vendor said no; its words may hold a key
        raise HTTPException(502, f"the service refused the request ({type(exc).__name__})") from exc
    return {"ok": bool(result.get("ok")), "result": result}
