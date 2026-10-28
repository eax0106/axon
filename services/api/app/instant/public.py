"""Endpoints that other systems call, each authenticated its own way: the website intake URL
(per-employee secret), Meta's lead webhook (verify token and HMAC), and Vobiz call-end callbacks
(signature)."""

import hmac
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import parse_qs

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import Session
from app.instant import dialer, intake
from app.models import Call, Employee, IntakeStatus, LeadConnection, LeadIntakeEntry
from app.providers.base import ProviderKind, TelephonyProvider
from app.providers.leads.meta_lead_ads import MetaLeadAds
from app.providers.registry import require
from app.settings import api_public_url

router = APIRouter()
log = logging.getLogger("axon.instant")

SECRET_HEADER = "X-Axon-Lead-Secret"  # noqa: S105 - a header name
NONCE_TTL_S = 300.0
_seen_nonces: dict[str, float] = {}  # ponytail: per process; shared store if the API scales out


def intake_response(result: intake.Result) -> JSONResponse:
    code = {
        IntakeStatus.ACCEPTED: status.HTTP_202_ACCEPTED,
        IntakeStatus.DEDUPLICATED: status.HTTP_200_OK,
        IntakeStatus.REJECTED: 422,
    }[result.status]
    body = {
        "status": result.status.value,
        "reason": result.reason,
        "lead_id": str(result.lead_id) if result.lead_id else None,
        "call_id": str(result.call_id) if result.call_id else None,
    }
    return JSONResponse(body, status_code=code)


def meta() -> MetaLeadAds:
    provider = require(ProviderKind.LEADS)
    assert isinstance(provider, MetaLeadAds)
    return provider


@router.get("/lead-intake/meta")
async def meta_verify(
    mode: Annotated[str, Query(alias="hub.mode")] = "",
    verify_token: Annotated[str, Query(alias="hub.verify_token")] = "",
    challenge: Annotated[str, Query(alias="hub.challenge")] = "",
) -> PlainTextResponse:
    """Meta checks this URL when the webhook is set up."""
    answer = meta().challenge(mode, verify_token, challenge)
    if answer is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "verify token does not match")
    return PlainTextResponse(answer)


@router.post("/lead-intake/meta")
async def meta_leads(request: Request, session: Session) -> dict[str, int]:
    provider = meta()
    raw = await request.body()
    if not provider.valid_signature(raw, request.headers.get("x-hub-signature-256")):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad signature")
    try:
        events = provider.events(await request.json())
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "not JSON") from exc
    handled = 0
    for event in events:
        connection = await session.scalar(
            select(LeadConnection).where(LeadConnection.meta_form_id == event.form_id)
        )
        if connection is None or not connection.meta_page_token:
            continue  # a form nobody here connected
        employee = await session.get(Employee, connection.employee_id)
        assert employee is not None  # FK guarantees it
        account_id, employee_id = (
            employee.account_id,
            employee.id,
        )  # still readable after a rollback
        try:
            fields = await provider.fetch_lead(event.leadgen_id, connection.meta_page_token)
            await intake.process(session, employee, fields, source="meta", now=datetime.now(UTC))
        except Exception as exc:
            # One bad form (revoked token, squatter) must not fail the batch for everyone else:
            # Meta would retry the whole thing. Say so in the owner's intake log instead.
            await session.rollback()
            log.warning("meta lead %s failed: %s", event.leadgen_id, type(exc).__name__)
            session.add(
                LeadIntakeEntry(
                    account_id=account_id,
                    employee_id=employee_id,
                    source="meta",
                    status=IntakeStatus.REJECTED,
                    reason=f"could not read the lead from Meta ({type(exc).__name__})",
                )
            )
            await session.commit()
            continue
        handled += 1
    return {"handled": handled}


@router.post("/lead-intake/{connection_id}")
async def website_intake(
    connection_id: uuid.UUID,
    request: Request,
    session: Session,
    secret: Annotated[str | None, Header(alias=SECRET_HEADER)] = None,
) -> JSONResponse:
    """Website (or Zapier / Pabbly / n8n) posts one lead as JSON: a phone and any other fields."""
    connection = await session.get(LeadConnection, connection_id)
    if connection is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown intake URL")
    if not hmac.compare_digest((secret or "").encode(), connection.secret.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"missing or wrong {SECRET_HEADER}")
    try:
        payload: Any = await request.json()
    except ValueError as exc:
        raise HTTPException(422, "body must be JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(422, "body must be a JSON object")
    employee = await session.get(Employee, connection.employee_id)
    assert employee is not None  # FK guarantees it
    result = await intake.process(
        session, employee, payload, source="website", now=datetime.now(UTC)
    )
    return intake_response(result)


def _fresh(nonce: str, now: float) -> bool:
    for old in [n for n, expiry in _seen_nonces.items() if expiry < now]:
        del _seen_nonces[old]
    if nonce in _seen_nonces:
        return False
    _seen_nonces[nonce] = now + NONCE_TTL_S
    return True


@router.post("/vobiz/events")
async def vobiz_events(request: Request) -> Response:
    """Vobiz tells us a call ended. The signature covers only the URL and a nonce, so nothing in
    the body is believed: it only names the call, and what happened comes from the carrier's own
    record (the CDR), fetched with our credentials."""
    telephony = require(ProviderKind.TELEPHONY)
    assert isinstance(telephony, TelephonyProvider)
    url = api_public_url() + "/vobiz/events"
    if not telephony.callback_is_authentic(url, request.headers):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad signature")
    nonce = request.headers.get("x-vobiz-signature-v3-nonce", "")
    if not _fresh(nonce, time.time()):
        raise HTTPException(status.HTTP_409_CONFLICT, "nonce already used")
    form = parse_qs((await request.body()).decode("utf-8", "replace"))
    leg_id = (form.get("CallUUID") or [""])[0]
    ids = [i for i in (leg_id, (form.get("RequestUUID") or [""])[0]) if i]
    factory = async_sessionmaker(request.app.state.db, expire_on_commit=False)
    async with factory() as session:
        call = await session.scalar(
            select(Call).where(or_(Call.carrier_call_id.in_(ids), Call.carrier_leg_id.in_(ids)))
        )
    if call is not None:
        await dialer.settle_from_carrier(
            factory, telephony, call.id, datetime.now(UTC), leg_id=leg_id or None
        )
    return Response(status_code=status.HTTP_200_OK)
