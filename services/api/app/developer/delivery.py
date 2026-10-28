"""Sending events to developers' servers: the signature, the retries, the log.

Every event is signed with HMAC-SHA256 over `<unix time>.<body>` (the time is in the header, so a
receiver can refuse a replay), sent once, and retried on a ladder when the receiver does not
answer 2xx. Each send is a row (`WebhookDelivery`) the owner can read, resend and test.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import any_, delete, literal, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.actions import net
from app.developer import events
from app.developer.result_webhook import ResultWebhook
from app.employees import service
from app.employees.script import ScriptBundle
from app.models import (
    ApiRequest,
    DeliveryStatus,
    WebhookDelivery,
    WebhookEndpoint,
    WebhookEvent,
)

log = logging.getLogger("axon.webhooks")

SIGNATURE_HEADER = "X-Axon-Signature"
RETRY_AFTER_S = (60, 300, 1800, 7200, 21600)  # before attempts 2 to 6
MAX_ATTEMPTS = len(RETRY_AFTER_S) + 1
LEASE = timedelta(minutes=5)  # a claimed send that never reports is tried again after this
TIMEOUT_S = 10
BATCH = 20
KEEP = timedelta(days=30)  # events, their deliveries and the request log are kept this long

# Tests only: a transport to send through instead of the network. Never set in the app.
TRANSPORT: httpx.AsyncBaseTransport | None = None


def new_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def body_of(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()


def sign(secret: str, body: bytes, at: int) -> str:
    """The header value: `t=<unix time>,v1=<hex>`. Verify by computing HMAC-SHA256 of
    `<t>.<raw body>` with the secret and comparing in constant time."""
    digest = hmac.new(secret.encode(), f"{at}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={at},v1={digest}"


@dataclass(frozen=True)
class Sent:
    status: int | None
    error: str | None  # None = the receiver answered 2xx


async def send(url: str, body: bytes, headers: dict[str, str]) -> Sent:
    """One POST. The address is checked and pinned like the AI's HTTP tool (a server of ours is
    never a target), redirects are not followed and the answer is never read."""
    try:
        async with asyncio.timeout(TIMEOUT_S):
            pinned, headers["Host"], host = await net.pin(url)
            async with (
                httpx.AsyncClient(timeout=TIMEOUT_S, transport=TRANSPORT) as client,
                client.stream(
                    "POST", pinned, content=body, headers=headers,
                    extensions={"sni_hostname": host},
                ) as response,
            ):  # fmt: skip
                status = response.status_code
    except net.BlockedError as exc:
        return Sent(None, str(exc))
    except TimeoutError:
        return Sent(None, "no answer in time")
    except httpx.HTTPError as exc:
        return Sent(None, f"could not connect ({type(exc).__name__})")
    return Sent(status, None if 200 <= status < 300 else f"the receiver answered {status}")


def request_headers(delivery: WebhookDelivery) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "User-Agent": "Axon-Webhooks/1",
        "X-Axon-Event": delivery.event,
        "X-Axon-Delivery": str(delivery.id),
    }


async def _target(session: AsyncSession, delivery: WebhookDelivery) -> tuple[str, str | None] | str:
    """The address and secret to use now, or why the send is pointless. An account endpoint is read
    at send time, so an edit or a rotation reaches the retries."""
    if delivery.endpoint_id is None:
        return delivery.target_url, delivery.target_secret
    endpoint = await session.get(WebhookEndpoint, delivery.endpoint_id)
    if endpoint is None:
        return "the endpoint was removed"
    if not endpoint.active and not delivery.is_test:
        return "the endpoint is switched off"
    return endpoint.url, endpoint.secret


def record(delivery: WebhookDelivery, sent: Sent, now: datetime) -> None:
    """Write how an attempt went and decide what happens next."""
    delivery.attempts += 1
    delivery.response_code, delivery.last_error = sent.status, sent.error
    if sent.error is None:
        delivery.status, delivery.delivered_at, delivery.next_attempt_at = (
            DeliveryStatus.DELIVERED,
            now,
            None,
        )
    elif delivery.is_test or delivery.attempts >= MAX_ATTEMPTS:
        delivery.status, delivery.next_attempt_at = DeliveryStatus.FAILED, None
    else:
        delivery.next_attempt_at = now + timedelta(seconds=RETRY_AFTER_S[delivery.attempts - 1])


async def run_one(
    factory: async_sessionmaker[AsyncSession], delivery_id: uuid.UUID, now: datetime
) -> WebhookDelivery | None:
    """Attempt one delivery. The row is read, the send happens with no transaction open, and the
    result is written after."""
    async with factory() as session:
        delivery = await session.get(WebhookDelivery, delivery_id)
        if delivery is None or delivery.status is not DeliveryStatus.PENDING:
            return delivery
        target = await _target(session, delivery)
        await session.commit()  # nothing is held while the receiver takes its time
        if isinstance(target, str):
            delivery.attempts += 1
            delivery.status, delivery.last_error, delivery.next_attempt_at = (
                DeliveryStatus.FAILED,
                target,
                None,
            )
        else:
            url, secret = target
            delivery.target_url = url
            body = body_of(delivery.payload)
            headers = request_headers(delivery)
            if secret:
                headers[SIGNATURE_HEADER] = sign(secret, body, int(time.time()))
            record(delivery, await send(url, body, headers), now)
        await session.commit()
        return delivery


async def fan_out(factory: async_sessionmaker[AsyncSession], now: datetime) -> int:
    """Turn new events into deliveries: one for every active endpoint of the account that
    subscribed to the type, and the employee's own result webhook for a call that reached a
    person. Returns how many events were taken."""
    async with factory() as session:
        taken = list(
            await session.scalars(
                select(WebhookEvent)
                .where(WebhookEvent.fanned_out_at.is_(None))
                .order_by(WebhookEvent.created_at)
                .limit(BATCH * 5)
                .with_for_update(skip_locked=True)
            )
        )
        for event in taken:
            payload = events.envelope(
                event.id, event.type, event.created_at, event.account_id, event.data
            )
            endpoints = await session.scalars(
                select(WebhookEndpoint).where(
                    WebhookEndpoint.account_id == event.account_id,
                    WebhookEndpoint.active.is_(True),
                    literal(event.type) == any_(WebhookEndpoint.events),
                )
            )
            for endpoint in endpoints:
                session.add(_delivery(event, payload, now, endpoint=endpoint))
            if hook := await _result_webhook(session, event):
                session.add(_delivery(event, payload, now, hook=hook))
            event.fanned_out_at = now
        await session.commit()
    return len(taken)


def _delivery(
    event: WebhookEvent,
    payload: dict[str, Any],
    now: datetime,
    *,
    endpoint: WebhookEndpoint | None = None,
    hook: tuple[uuid.UUID, ResultWebhook] | None = None,
) -> WebhookDelivery:
    employee_id, config = hook if hook else (None, None)
    return WebhookDelivery(
        id=uuid.uuid4(),
        account_id=event.account_id,
        event_id=event.id,
        endpoint_id=endpoint.id if endpoint else None,
        employee_id=employee_id,
        target_url=endpoint.url if endpoint else config.url if config else "",
        target_secret=(config.secret or None) if config else None,
        event=event.type,
        payload=payload,
        status=DeliveryStatus.PENDING,
        next_attempt_at=now,
    )


async def published_hook(session: AsyncSession, employee_id: uuid.UUID) -> ResultWebhook | None:
    """The result webhook of the employee's latest published version, if it has one."""
    live = await service.latest_version(session, employee_id)
    return ScriptBundle.model_validate(live.bundle).result_webhook if live else None


async def _result_webhook(
    session: AsyncSession, event: WebhookEvent
) -> tuple[uuid.UUID, ResultWebhook] | None:
    """The employee's result webhook as published, if this call is one it wants."""
    if event.employee_id is None or event.type not in events.CONNECTED:
        return None
    config = await published_hook(session, event.employee_id)
    if config is None or not config.wants(voicemail=bool(event.data["call"]["voicemail"])):
        return None
    return event.employee_id, config


async def deliver_due(factory: async_sessionmaker[AsyncSession], now: datetime) -> int:
    """Send the deliveries that are due. Each is first leased (pushed out by LEASE) so no other
    worker takes it and a worker that dies mid-send does not strand it."""
    # shortcut: one queue for every account (BATCH sends per tick, each up to TIMEOUT_S), so a
    # receiver that times out slows the others; cap the sends in flight per endpoint when it does.
    async with factory() as session:
        due = list(
            await session.scalars(
                select(WebhookDelivery)
                .where(
                    WebhookDelivery.status == DeliveryStatus.PENDING,
                    WebhookDelivery.next_attempt_at <= now,
                )
                .order_by(WebhookDelivery.next_attempt_at)
                .limit(BATCH)
                .with_for_update(skip_locked=True)
            )
        )
        for delivery in due:
            delivery.next_attempt_at = now + LEASE
        await session.commit()
    results = await asyncio.gather(
        *(run_one(factory, d.id, now) for d in due), return_exceptions=True
    )
    for result in results:
        if isinstance(result, BaseException):
            log.error("webhook delivery crashed: %s", type(result).__name__)
    return len(due)


async def send_test(
    session: AsyncSession,
    account_id: uuid.UUID,
    type_: str,
    now: datetime,
    *,
    endpoint: WebhookEndpoint | None = None,
    hook: tuple[uuid.UUID, ResultWebhook] | None = None,
) -> WebhookDelivery:
    """Queue an example of an event for one address only (it is marked taken, so fan-out leaves it
    alone). Commits."""
    event = events.record(
        session, account_id, type_, events.sample(type_), hook[0] if hook else None
    )
    event.fanned_out_at = now
    await session.flush()  # the event row first: the delivery points at it
    payload = events.envelope(event.id, type_, now, account_id, event.data, test=True)
    test = _delivery(event, payload, now, endpoint=endpoint, hook=hook)
    test.is_test = True
    session.add(test)
    await session.commit()
    return test


async def run_test(
    factory: async_sessionmaker[AsyncSession], test: WebhookDelivery, now: datetime
) -> dict[str, Any]:
    """Send a test delivery now (no retries) and say what the receiver answered."""
    done = await run_one(factory, test.id, now)
    assert done is not None  # it was committed a moment ago
    return {
        "delivery_id": str(done.id),
        "delivered": done.status is DeliveryStatus.DELIVERED,
        "response_code": done.response_code,
        "error": done.last_error,
    }


def resend(
    delivery: WebhookDelivery, now: datetime, hook: ResultWebhook | None = None
) -> WebhookDelivery:
    """The same event to the same place again, as a new row: the first attempt stays in the log.
    A result webhook goes to where it points now (`hook`), like an account endpoint does."""
    return WebhookDelivery(
        id=uuid.uuid4(),
        account_id=delivery.account_id,
        event_id=delivery.event_id,
        endpoint_id=delivery.endpoint_id,
        employee_id=delivery.employee_id,
        target_url=hook.url if hook else delivery.target_url,
        target_secret=(hook.secret or None) if hook else delivery.target_secret,
        event=delivery.event,
        payload=delivery.payload,
        is_test=delivery.is_test,
        status=DeliveryStatus.PENDING,
        next_attempt_at=now,
    )


async def prune(factory: async_sessionmaker[AsyncSession], now: datetime) -> int:
    """Forget the request log, and the events and deliveries, that are older than KEEP."""
    async with factory() as session:
        old_requests = await session.execute(
            delete(ApiRequest).where(ApiRequest.created_at < now - KEEP)
        )
        old_events = await session.execute(
            delete(WebhookEvent).where(
                WebhookEvent.created_at < now - KEEP, WebhookEvent.fanned_out_at.is_not(None)
            )
        )  # the deliveries of an event go with it
        await session.commit()
    return int(old_requests.rowcount or 0) + int(old_events.rowcount or 0)  # type: ignore[attr-defined]
