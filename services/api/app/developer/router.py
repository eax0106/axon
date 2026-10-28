"""The developer pages' endpoints, for people signed in to the dashboard: API keys, webhook
endpoints, the delivery log, the request log, and the API's status. Everyone in the account can
read; only the owner changes anything."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.actions import net
from app.auth import CurrentUser, not_impersonating
from app.db import Session
from app.developer import delivery, events, keys, paging
from app.developer.paging import Page
from app.employees.limits import take
from app.employees.router import OwnerUser
from app.models import (
    ApiKey,
    ApiRequest,
    DeliveryStatus,
    WebhookDelivery,
    WebhookEndpoint,
)

router = APIRouter(prefix="/developer")
MAX_ENDPOINTS = 10
TESTS_PER_HOUR = 30


# --- API keys -----------------------------------------------------------------------------------


class KeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class KeyOut(BaseModel):
    id: uuid.UUID
    name: str
    prefix: str  # the start of the key, enough to tell keys apart
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class KeyCreated(KeyOut):
    key: str  # the whole key. This is the only time it is shown.


def _key_out(key: ApiKey) -> KeyOut:
    return KeyOut(
        id=key.id,
        name=key.name,
        prefix=key.prefix,
        last_used_at=key.last_used_at,
        revoked_at=key.revoked_at,
        created_at=key.created_at,
    )


@router.post(
    "/keys", status_code=status.HTTP_201_CREATED, dependencies=[Depends(not_impersonating)]
)
async def create_key(body: KeyCreate, user: OwnerUser, session: Session) -> KeyCreated:
    account_id = user.account_id
    active = await session.scalar(
        select(func.count())
        .select_from(ApiKey)
        .where(ApiKey.account_id == account_id, ApiKey.revoked_at.is_(None))
    )
    if (active or 0) >= keys.MAX_ACTIVE_KEYS:
        raise HTTPException(409, f"{keys.MAX_ACTIVE_KEYS} keys are in use: revoke one first")
    key, prefix, hashed = keys.new_key()
    row = ApiKey(account_id=account_id, name=body.name, prefix=prefix, key_hash=hashed)
    session.add(row)
    await session.commit()
    return KeyCreated(**_key_out(row).model_dump(), key=key)


@router.get("/keys")
async def list_keys(user: CurrentUser, session: Session) -> list[KeyOut]:
    rows = await session.scalars(
        select(ApiKey).where(ApiKey.account_id == user.account_id).order_by(ApiKey.created_at)
    )
    return [_key_out(k) for k in rows]


@router.delete("/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_key(key_id: uuid.UUID, user: OwnerUser, session: Session) -> None:
    """Stop the key working now. The row stays, so the request log can still name it."""
    key = await session.scalar(
        select(ApiKey).where(ApiKey.id == key_id, ApiKey.account_id == user.account_id)
    )
    if key is None:
        raise HTTPException(404, "no such key")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
        await session.commit()


# --- Webhook endpoints --------------------------------------------------------------------------


def _check_url(value: str) -> str:
    problem = net.url_problem(value)
    if problem:
        raise ValueError(problem)
    return value


def _check_events(value: list[str]) -> list[str]:
    unknown = [e for e in value if e not in events.EVENT_TYPES]
    if unknown:
        raise ValueError(f"unknown event {unknown[0]!r}; use {', '.join(events.EVENT_TYPES)}")
    if not value or len(set(value)) != len(value):
        raise ValueError("choose at least one event, each once")
    return value


class WebhookCreate(BaseModel):
    url: str = Field(max_length=500)
    events: list[str]
    description: str | None = Field(default=None, max_length=200)

    _url = field_validator("url")(lambda v: _check_url(v))
    _events = field_validator("events")(lambda v: _check_events(v))


class WebhookUpdate(BaseModel):
    url: str | None = Field(default=None, max_length=500)
    events: list[str] | None = None
    description: str | None = Field(default=None, max_length=200)
    active: bool | None = None

    @field_validator("url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        return None if value is None else _check_url(value)

    @field_validator("events")
    @classmethod
    def _events(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _check_events(value)


class WebhookOut(BaseModel):
    id: uuid.UUID
    url: str
    events: list[str]
    description: str | None
    active: bool
    created_at: datetime


class WebhookCreated(WebhookOut):
    secret: str  # signs every send. This is the only time it is shown, until it is rotated.


def _webhook_out(row: WebhookEndpoint) -> WebhookOut:
    return WebhookOut(
        id=row.id,
        url=row.url,
        events=list(row.events),
        description=row.description,
        active=row.active,
        created_at=row.created_at,
    )


async def _endpoint(
    session: AsyncSession, user_account: uuid.UUID, endpoint_id: uuid.UUID
) -> WebhookEndpoint:
    row = await session.scalar(
        select(WebhookEndpoint).where(
            WebhookEndpoint.id == endpoint_id, WebhookEndpoint.account_id == user_account
        )
    )
    if row is None:
        raise HTTPException(404, "no such webhook")
    return row


@router.post(
    "/webhooks", status_code=status.HTTP_201_CREATED, dependencies=[Depends(not_impersonating)]
)
async def create_webhook(body: WebhookCreate, user: OwnerUser, session: Session) -> WebhookCreated:
    account_id = user.account_id
    count = await session.scalar(
        select(func.count())
        .select_from(WebhookEndpoint)
        .where(WebhookEndpoint.account_id == account_id)
    )
    if (count or 0) >= MAX_ENDPOINTS:
        raise HTTPException(409, f"{MAX_ENDPOINTS} webhooks already: delete one first")
    row = WebhookEndpoint(
        account_id=account_id,
        url=body.url,
        events=body.events,
        description=body.description,
        secret=delivery.new_secret(),
    )
    session.add(row)
    await session.commit()
    return WebhookCreated(**_webhook_out(row).model_dump(), secret=row.secret)


@router.get("/webhooks")
async def list_webhooks(user: CurrentUser, session: Session) -> list[WebhookOut]:
    rows = await session.scalars(
        select(WebhookEndpoint)
        .where(WebhookEndpoint.account_id == user.account_id)
        .order_by(WebhookEndpoint.created_at)
    )
    return [_webhook_out(r) for r in rows]


@router.get("/webhooks/{endpoint_id}")
async def get_webhook(endpoint_id: uuid.UUID, user: CurrentUser, session: Session) -> WebhookOut:
    return _webhook_out(await _endpoint(session, user.account_id, endpoint_id))


@router.patch("/webhooks/{endpoint_id}", dependencies=[Depends(not_impersonating)])
async def update_webhook(
    endpoint_id: uuid.UUID, body: WebhookUpdate, user: OwnerUser, session: Session
) -> WebhookOut:
    row = await _endpoint(session, user.account_id, endpoint_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is None and field != "description":
            raise HTTPException(422, f"{field} cannot be null")
        setattr(row, field, value)
    await session.commit()
    return _webhook_out(row)


@router.delete("/webhooks/{endpoint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(endpoint_id: uuid.UUID, user: OwnerUser, session: Session) -> None:
    await session.delete(await _endpoint(session, user.account_id, endpoint_id))
    await session.commit()


@router.post("/webhooks/{endpoint_id}/rotate-secret")
async def rotate_secret(
    endpoint_id: uuid.UUID, user: OwnerUser, session: Session
) -> dict[str, str]:
    """A new signing secret, effective at once, also for sends that are waiting to be retried."""
    row = await _endpoint(session, user.account_id, endpoint_id)
    row.secret = delivery.new_secret()
    await session.commit()
    return {"secret": row.secret}


class TestBody(BaseModel):
    event: str = events.CALL_COMPLETED


@router.post("/webhooks/{endpoint_id}/test")
async def test_webhook(
    endpoint_id: uuid.UUID, body: TestBody, request: Request, user: OwnerUser, session: Session
) -> dict[str, Any]:
    """Send an example of an event to this address now and say what the receiver answered."""
    if body.event not in events.EVENT_TYPES:
        raise HTTPException(422, f"unknown event; use {', '.join(events.EVENT_TYPES)}")
    row = await _endpoint(session, user.account_id, endpoint_id)
    await take(session, user, "webhook.test", TESTS_PER_HOUR)
    now = datetime.now(UTC)
    test = await delivery.send_test(session, user.account_id, body.event, now, endpoint=row)
    factory = async_sessionmaker(request.app.state.db, expire_on_commit=False)
    return await delivery.run_test(factory, test, now)


# --- Deliveries ---------------------------------------------------------------------------------


class DeliveryOut(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    event: str
    endpoint_id: uuid.UUID | None  # none for an employee's result webhook
    employee_id: uuid.UUID | None
    url: str
    status: str  # pending | delivered | failed
    is_test: bool
    attempts: int
    response_code: int | None
    last_error: str | None
    next_attempt_at: datetime | None
    created_at: datetime
    delivered_at: datetime | None


class DeliveryDetail(DeliveryOut):
    payload: dict[str, Any]  # exactly what is sent


def _delivery_out(row: WebhookDelivery) -> DeliveryOut:
    return DeliveryOut(
        id=row.id,
        event_id=row.event_id,
        event=row.event,
        endpoint_id=row.endpoint_id,
        employee_id=row.employee_id,
        url=row.target_url,
        status=row.status.value,
        is_test=row.is_test,
        attempts=row.attempts,
        response_code=row.response_code,
        last_error=row.last_error,
        next_attempt_at=row.next_attempt_at,
        created_at=row.created_at,
        delivered_at=row.delivered_at,
    )


async def _delivery(
    session: AsyncSession, account_id: uuid.UUID, delivery_id: uuid.UUID
) -> WebhookDelivery:
    row = await session.scalar(
        select(WebhookDelivery).where(
            WebhookDelivery.id == delivery_id, WebhookDelivery.account_id == account_id
        )
    )
    if row is None:
        raise HTTPException(404, "no such delivery")
    return row


@router.get("/deliveries")
async def list_deliveries(
    user: CurrentUser,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=paging.MAX_LIMIT)] = 25,
    cursor: str | None = None,
    endpoint_id: uuid.UUID | None = None,
    employee_id: uuid.UUID | None = None,
    event: str | None = None,
    delivery_status: Annotated[DeliveryStatus | None, Query(alias="status")] = None,
) -> Page[DeliveryOut]:
    query = select(WebhookDelivery).where(WebhookDelivery.account_id == user.account_id)
    if endpoint_id:
        query = query.where(WebhookDelivery.endpoint_id == endpoint_id)
    if employee_id:
        query = query.where(WebhookDelivery.employee_id == employee_id)
    if event:
        query = query.where(WebhookDelivery.event == event)
    if delivery_status:
        query = query.where(WebhookDelivery.status == delivery_status)
    if cursor:
        at, last = paging.decode(cursor)
        query = query.where(
            tuple_(WebhookDelivery.created_at, WebhookDelivery.id) < tuple_(at, last)
        )
    rows = list(
        await session.scalars(
            query.order_by(WebhookDelivery.created_at.desc(), WebhookDelivery.id.desc()).limit(
                limit + 1
            )
        )
    )
    more = len(rows) > limit
    rows = rows[:limit]
    return Page(
        data=[_delivery_out(r) for r in rows],
        next_cursor=paging.encode(rows[-1].created_at, rows[-1].id) if more else None,
    )


@router.get("/deliveries/{delivery_id}")
async def get_delivery(
    delivery_id: uuid.UUID, user: CurrentUser, session: Session
) -> DeliveryDetail:
    row = await _delivery(session, user.account_id, delivery_id)
    return DeliveryDetail(**_delivery_out(row).model_dump(), payload=row.payload)


@router.post("/deliveries/{delivery_id}/resend", status_code=status.HTTP_201_CREATED)
async def resend_delivery(delivery_id: uuid.UUID, user: OwnerUser, session: Session) -> DeliveryOut:
    """Send the same event again as a new delivery (the first stays in the log)."""
    row = await _delivery(session, user.account_id, delivery_id)
    if row.status is DeliveryStatus.PENDING:
        raise HTTPException(409, "it is still being sent: wait for the result first")
    hook = None
    if row.endpoint_id is None and row.employee_id and not row.is_test:
        hook = await delivery.published_hook(session, row.employee_id)
        if hook is None:
            raise HTTPException(409, "the employee has no result webhook any more")
    again = delivery.resend(row, datetime.now(UTC), hook)
    session.add(again)
    await session.commit()
    return _delivery_out(again)


# --- Request log and status ---------------------------------------------------------------------


class RequestOut(BaseModel):
    id: int
    key_id: uuid.UUID | None
    method: str
    path: str
    status_code: int
    duration_ms: int
    created_at: datetime


@router.get("/requests")
async def list_requests(
    user: CurrentUser,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=paging.MAX_LIMIT)] = 50,
    before: Annotated[int | None, Query(description="Rows older than this id.")] = None,
    key_id: uuid.UUID | None = None,
    min_status: Annotated[int | None, Query(ge=100, le=599)] = None,
) -> list[RequestOut]:
    query = select(ApiRequest).where(ApiRequest.account_id == user.account_id)
    if key_id:
        query = query.where(ApiRequest.key_id == key_id)
    if min_status:
        query = query.where(ApiRequest.status_code >= min_status)
    if before:
        query = query.where(ApiRequest.id < before)
    rows = await session.scalars(query.order_by(ApiRequest.id.desc()).limit(limit))
    return [
        RequestOut(
            id=r.id,
            key_id=r.key_id,
            method=r.method,
            path=r.path,
            status_code=r.status_code,
            duration_ms=r.duration_ms,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/status")
async def api_status(user: CurrentUser, session: Session) -> dict[str, Any]:
    """How the API and the webhooks are doing for this account over the last day."""
    since = datetime.now(UTC) - timedelta(days=1)
    account = user.account_id
    requests = (
        await session.execute(
            select(func.count(), func.count().filter(ApiRequest.status_code >= 500))
            .select_from(ApiRequest)
            .where(ApiRequest.account_id == account, ApiRequest.created_at >= since)
        )
    ).one()
    counted = await session.execute(
        select(WebhookDelivery.status, func.count())
        .where(WebhookDelivery.account_id == account, WebhookDelivery.created_at >= since)
        .group_by(WebhookDelivery.status)
    )
    by_status = {state: n for state, n in counted.all()}
    oldest = await session.scalar(
        select(func.min(WebhookDelivery.next_attempt_at)).where(
            WebhookDelivery.account_id == account, WebhookDelivery.status == DeliveryStatus.PENDING
        )
    )
    return {
        "api": {"version": "v1", "status": "operational"},
        "requests_24h": requests[0],
        "server_errors_24h": requests[1],
        "webhooks_24h": {
            "delivered": by_status.get(DeliveryStatus.DELIVERED, 0),
            "failed": by_status.get(DeliveryStatus.FAILED, 0),
            "pending": by_status.get(DeliveryStatus.PENDING, 0),
            "next_attempt_at": oldest,
        },
    }


@router.get("/events")
async def list_events(_: CurrentUser) -> list[dict[str, Any]]:
    """The events that can be subscribed to, each with an example of its `data`."""
    return [
        {"type": t, "description": events.DESCRIPTIONS[t], "example": events.sample(t)}
        for t in events.EVENT_TYPES
    ]
