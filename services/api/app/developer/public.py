"""The public REST API, version 1: what a developer's own systems call with an API key.

It is deliberately small: read the account, employees, calls, leads and campaigns, and hand a new
lead to an Instant employee. Its shapes are in `shapes.py` and never change under a client; a
breaking change would be a /v2. The OpenAPI document and the Postman collection are built from
these same routes, so they cannot drift from what the API does.
"""

import json
import logging
import time
import uuid
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, TypeAdapter
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db import Session
from app.developer import events, paging, shapes
from app.developer.keys import Authenticated
from app.developer.paging import Page
from app.employees import service
from app.instant import intake
from app.instant.public import intake_response
from app.models import (
    Account,
    ApiRequest,
    Call,
    Campaign,
    CampaignStatus,
    Direction,
    Employee,
    Lead,
    PhoneNumber,
)

log = logging.getLogger("axon.api")
VERSION = "1"
DESCRIPTION = (
    "Read your Axon account and hand new leads to an AI employee. Authenticate every request "
    "with an API key: `Authorization: Bearer axk_live_...`. At most 120 requests a minute per "
    "key; over that you get 429 and a `Retry-After` header. Lists are newest first and paged "
    "with `cursor`. Events we send to your servers are described under `webhooks`; verify "
    "their `X-Axon-Signature` header before you trust them."
)


class LoggedRoute(APIRoute):
    """Writes one row to the request log for every request that got as far as an API key."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handle = super().get_route_handler()

        async def logged(request: Request) -> Response:
            started, code = time.monotonic(), 500
            try:
                response = await handle(request)
                code = response.status_code
                return response
            except HTTPException as exc:
                code = exc.status_code
                raise
            except RequestValidationError:
                code = 422
                raise
            finally:
                await _log(request, code, round((time.monotonic() - started) * 1000))

        return logged


async def _log(request: Request, code: int, duration_ms: int) -> None:
    auth = getattr(request.state, "api_auth", None)
    if auth is None:  # refused before we knew whose key it was: there is no account to show it to
        return
    path = request.scope["route"].path if request.scope.get("route") else request.url.path
    try:
        factory = async_sessionmaker(request.app.state.db, expire_on_commit=False)
        async with factory() as session:
            session.add(
                ApiRequest(
                    account_id=auth.account_id,
                    key_id=auth.key_id,
                    method=request.method,
                    path=path[:300],
                    status_code=code,
                    duration_ms=duration_ms,
                )
            )
            await session.commit()
    except Exception as exc:
        log.warning("request log write failed: %s", type(exc).__name__)


router = APIRouter(prefix="/v1", route_class=LoggedRoute)
docs = APIRouter(prefix="/v1", tags=["docs"])


class AccountOut(BaseModel):
    id: uuid.UUID
    name: str
    credit_balance: str  # credits, as a decimal string; 1 credit = Rs 1


class EmployeeOut(BaseModel):
    id: uuid.UUID
    name: str
    role_title: str | None
    channel: str
    purpose: str
    status: str  # draft | training | live | paused
    language: str
    extra_languages: list[str]
    phone_number: str | None  # the number it answers on and dials from
    pre_call_variables: list[str]  # the lead fields it can use, and the ones to send in a lead


class IntakeOut(BaseModel):
    status: Literal["accepted", "deduplicated", "rejected"]
    reason: str | None
    lead_id: uuid.UUID | None
    call_id: uuid.UUID | None


Limit = Annotated[int, Query(ge=1, le=paging.MAX_LIMIT, description="Rows per page.")]
Cursor = Annotated[str | None, Query(description="`next_cursor` of the previous page.")]


async def _employee_out(session: AsyncSession, employee: Employee) -> EmployeeOut:
    number = await session.get(PhoneNumber, employee.number_id) if employee.number_id else None
    return EmployeeOut(
        id=employee.id,
        name=employee.name,
        role_title=employee.role_title,
        channel=employee.channel.value,
        purpose=employee.purpose.value,
        status=employee.status.value,
        language=employee.language,
        extra_languages=employee.extra_languages,
        phone_number=number.e164 if number else None,
        pre_call_variables=service.bundle_of(employee).pre_call_variables,
    )


async def _employee(
    session: AsyncSession, account_id: uuid.UUID, employee_id: uuid.UUID
) -> Employee:
    employee = await session.scalar(
        select(Employee).where(Employee.id == employee_id, Employee.account_id == account_id)
    )
    if employee is None:
        raise HTTPException(404, "no such employee")
    return employee


@router.get("/account", tags=["account"], summary="Your account")
async def account(auth: Authenticated, session: Session) -> AccountOut:
    found = await session.get(Account, auth.account_id)
    assert found is not None  # the key's foreign key guarantees it
    return AccountOut(id=found.id, name=found.name, credit_balance=str(found.credit_balance))


@router.get("/employees", tags=["employees"], summary="List employees")
async def list_employees(auth: Authenticated, session: Session) -> list[EmployeeOut]:
    rows = await session.scalars(
        select(Employee).where(Employee.account_id == auth.account_id).order_by(Employee.created_at)
    )
    return [await _employee_out(session, e) for e in rows]


@router.get("/employees/{employee_id}", tags=["employees"], summary="Get one employee")
async def get_employee(
    employee_id: uuid.UUID, auth: Authenticated, session: Session
) -> EmployeeOut:
    return await _employee_out(session, await _employee(session, auth.account_id, employee_id))


@router.post(
    "/employees/{employee_id}/leads",
    tags=["leads"],
    summary="Send a lead to an Instant employee",
    status_code=202,
    responses={
        200: {"model": IntakeOut, "description": "Already received recently: nothing was done."},
        202: {"model": IntakeOut, "description": "Accepted: the first call is queued."},
        422: {"model": IntakeOut, "description": "Refused, with the reason."},
    },
)
async def submit_lead(
    employee_id: uuid.UUID,
    auth: Authenticated,
    session: Session,
    lead: Annotated[
        dict[str, Any],
        Body(
            description="A JSON object with `phone` (an Indian mobile number), optionally `name`, "
            "and any of the employee's `pre_call_variables`.",
            examples=[{"phone": "+919876543210", "name": "Asha", "budget": "80 lakh"}],
        ),
    ],
) -> JSONResponse:
    employee = await _employee(session, auth.account_id, employee_id)
    result = await intake.process(session, employee, lead, source="api", now=datetime.now(UTC))
    return intake_response(result)


@router.get("/leads", tags=["leads"], summary="List leads")
async def list_leads(
    auth: Authenticated,
    session: Session,
    limit: Limit = 25,
    cursor: Cursor = None,
    phone: Annotated[str | None, Query(description="Only this number, e.g. +919876543210.")] = None,
) -> Page[shapes.LeadOut]:
    query = select(Lead).where(Lead.account_id == auth.account_id)
    if phone:
        query = query.where(Lead.phone == phone)
    if cursor:
        at, last = paging.decode(cursor)
        query = query.where(tuple_(Lead.created_at, Lead.id) < tuple_(at, last))
    rows = list(
        await session.scalars(
            query.order_by(Lead.created_at.desc(), Lead.id.desc()).limit(limit + 1)
        )
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return Page(
        data=[shapes.lead_out(r, r.created_at) for r in rows],
        next_cursor=paging.encode(rows[-1].created_at, rows[-1].id) if more else None,
    )


@router.get("/leads/{lead_id}", tags=["leads"], summary="Get one lead")
async def get_lead(lead_id: uuid.UUID, auth: Authenticated, session: Session) -> shapes.LeadOut:
    lead = await session.scalar(
        select(Lead).where(Lead.id == lead_id, Lead.account_id == auth.account_id)
    )
    if lead is None:
        raise HTTPException(404, "no such lead")
    return shapes.lead_out(lead, lead.created_at)


@router.get("/calls", tags=["calls"], summary="List calls (test calls are not included)")
async def list_calls(
    auth: Authenticated,
    session: Session,
    limit: Limit = 25,
    cursor: Cursor = None,
    employee_id: uuid.UUID | None = None,
    direction: Direction | None = None,
    status: Annotated[str | None, Query(description="A call status, e.g. completed.")] = None,
    since: Annotated[datetime | None, Query(description="Only calls created at or after.")] = None,
) -> Page[shapes.CallOut]:
    query = (
        select(Call, Lead.phone)
        .outerjoin(Lead, Lead.id == Call.lead_id)
        .where(Call.account_id == auth.account_id, Call.is_test.is_(False))
    )
    if employee_id:
        query = query.where(Call.employee_id == employee_id)
    if direction:
        query = query.where(Call.direction == direction)
    if status:
        query = query.where(Call.status == status)
    if since:
        query = query.where(Call.created_at >= since)
    if cursor:
        at, last = paging.decode(cursor)
        query = query.where(tuple_(Call.created_at, Call.id) < tuple_(at, last))
    found = await session.execute(
        query.order_by(Call.created_at.desc(), Call.id.desc()).limit(limit + 1)
    )
    rows = list(found.all())
    more = len(rows) > limit
    rows = rows[:limit]
    return Page(
        data=[shapes.call_out(c, c.caller_phone or p) for c, p in rows],
        next_cursor=paging.encode(rows[-1][0].created_at, rows[-1][0].id) if more else None,
    )


@router.get("/calls/{call_id}", tags=["calls"], summary="Get one call with its transcript")
async def get_call(call_id: uuid.UUID, auth: Authenticated, session: Session) -> shapes.CallDetail:
    row = (
        await session.execute(
            select(Call, Lead.phone)
            .outerjoin(Lead, Lead.id == Call.lead_id)
            .where(Call.id == call_id, Call.account_id == auth.account_id, Call.is_test.is_(False))
        )
    ).first()
    if row is None:
        raise HTTPException(404, "no such call")
    call, phone = row
    base = shapes.call_out(call, call.caller_phone or phone)
    return shapes.CallDetail(**base.model_dump(), transcript=call.transcript or [])


@router.get("/campaigns", tags=["campaigns"], summary="List bulk campaigns")
async def list_campaigns(
    auth: Authenticated,
    session: Session,
    limit: Limit = 25,
    cursor: Cursor = None,
    status: CampaignStatus | None = None,
) -> Page[shapes.CampaignOut]:
    query = select(Campaign).where(Campaign.account_id == auth.account_id)
    if status:
        query = query.where(Campaign.status == status)
    if cursor:
        at, last = paging.decode(cursor)
        query = query.where(tuple_(Campaign.created_at, Campaign.id) < tuple_(at, last))
    rows = list(
        await session.scalars(
            query.order_by(Campaign.created_at.desc(), Campaign.id.desc()).limit(limit + 1)
        )
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return Page(
        data=[shapes.campaign_out(r, r.created_at) for r in rows],
        next_cursor=paging.encode(rows[-1].created_at, rows[-1].id) if more else None,
    )


@router.get("/campaigns/{campaign_id}", tags=["campaigns"], summary="Get one campaign")
async def get_campaign(
    campaign_id: uuid.UUID, auth: Authenticated, session: Session
) -> shapes.CampaignOut:
    found = await session.scalar(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.account_id == auth.account_id)
    )
    if found is None:
        raise HTTPException(404, "no such campaign")
    return shapes.campaign_out(found, found.created_at)


# --- The documents built from the routes above -------------------------------------------------


class EventEnvelope(BaseModel):
    id: uuid.UUID  # the same on every send and resend of one event: use it to ignore repeats
    type: str
    created_at: datetime
    account_id: uuid.UUID
    data: dict[str, Any]
    test: bool | None = None  # true on the test button's sends


class CallEventData(BaseModel):
    call: shapes.CallOut


class LeadEventData(BaseModel):
    lead: shapes.LeadOut


class CampaignEventData(BaseModel):
    campaign: shapes.CampaignOut
    previous_status: str


EVENT_DATA: dict[str, type[BaseModel]] = {
    events.CALL_COMPLETED: CallEventData,
    events.CALL_NOT_CONNECTED: CallEventData,
    events.INBOUND_ANSWERED: CallEventData,
    events.INBOUND_MISSED: CallEventData,
    events.LEAD_CREATED: LeadEventData,
    events.CAMPAIGN_STATUS: CampaignEventData,
}


def openapi_spec(base_url: str) -> dict[str, Any]:
    spec = get_openapi(
        title="Axon Voice Engine API",
        version=VERSION,
        summary="Public API and webhooks",
        description=DESCRIPTION,
        routes=router.routes,
        servers=[{"url": base_url}],
    )
    schemas = spec.setdefault("components", {}).setdefault("schemas", {})
    hooks: dict[str, Any] = {}
    for kind, model in EVENT_DATA.items():
        schema = TypeAdapter(model).json_schema(ref_template="#/components/schemas/{model}")
        schemas.update(schema.pop("$defs", {}))
        schemas[model.__name__] = schema
        hooks[kind] = {
            "post": {
                "summary": kind,
                "description": events.DESCRIPTIONS[kind]
                + " Answer with any 2xx within 10 seconds; anything else is retried.",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "allOf": [
                                    {"$ref": "#/components/schemas/EventEnvelope"},
                                    {
                                        "type": "object",
                                        "properties": {
                                            "data": {
                                                "$ref": f"#/components/schemas/{model.__name__}"
                                            }
                                        },
                                    },
                                ]
                            },
                            "example": events.envelope(
                                uuid.UUID(int=1),
                                kind,
                                datetime(2026, 1, 15, tzinfo=UTC),
                                uuid.UUID(int=2),
                                events.sample(kind),
                            ),
                        }
                    },
                },
                "responses": {"200": {"description": "Received."}},
            }
        }
    envelope_schema = TypeAdapter(EventEnvelope).json_schema(
        ref_template="#/components/schemas/{model}"
    )
    schemas["EventEnvelope"] = envelope_schema
    spec["webhooks"] = hooks
    return spec


def postman_collection(spec: dict[str, Any], base_url: str) -> dict[str, Any]:
    """A Postman collection (v2.1) with one request for every operation in the spec."""
    folders: dict[str, list[dict[str, Any]]] = {}
    for path, item in spec["paths"].items():
        for method, op in item.items():
            raw = path.replace("{", ":").replace("}", "")
            request: dict[str, Any] = {
                "method": method.upper(),
                "header": [{"key": "Accept", "value": "application/json"}],
                "url": {
                    "raw": "{{base_url}}" + raw,
                    "host": ["{{base_url}}"],
                    "path": [p for p in raw.split("/") if p],
                    "variable": [
                        {"key": p["name"], "value": ""}
                        for p in op.get("parameters", [])
                        if p["in"] == "path"
                    ],
                    "query": [
                        {"key": p["name"], "value": "", "disabled": True}
                        for p in op.get("parameters", [])
                        if p["in"] == "query"
                    ],
                },
            }
            body = op.get("requestBody", {}).get("content", {}).get("application/json")
            if body is not None:
                example = (body["schema"].get("examples") or [{}])[0]
                request["header"].append({"key": "Content-Type", "value": "application/json"})
                request["body"] = {"mode": "raw", "raw": _pretty(example)}
            folders.setdefault(op["tags"][0], []).append(
                {"name": op["summary"], "request": request}
            )
    return {
        "info": {
            "name": "Axon Voice Engine API",
            "description": DESCRIPTION,
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "auth": {
            "type": "bearer",
            "bearer": [{"key": "token", "value": "{{api_key}}", "type": "string"}],
        },
        "variable": [
            {"key": "base_url", "value": base_url},
            {"key": "api_key", "value": "axk_live_replace_me"},
        ],
        "item": [{"name": tag, "item": items} for tag, items in folders.items()],
    }


def _pretty(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


@docs.get("/openapi.json", summary="The OpenAPI document of this API")
async def openapi_json(request: Request) -> dict[str, Any]:
    return openapi_spec(str(request.base_url).rstrip("/"))


@docs.get("/postman.json", summary="A Postman collection of this API")
async def postman_json(request: Request) -> dict[str, Any]:
    base = str(request.base_url).rstrip("/")
    return postman_collection(openapi_spec(base), base)
