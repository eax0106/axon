"""Short-lived tickets for the browser test call.

The browser connects its audio WebSocket to the engine, which has no login. The API hands the
signed-in user a ticket (an HS256 token with its own `typ`, so it can never pass as a login
token and a login token can never open a call) that names one employee and one test-call row.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from app.auth import jwt_secret

TTL = timedelta(seconds=120)
TYPE = "web_call"


@dataclass(frozen=True)
class WebTicket:
    employee_id: uuid.UUID
    call_id: uuid.UUID
    account_id: uuid.UUID


def issue(ticket: WebTicket, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    claims = {
        "typ": TYPE,
        "employee": str(ticket.employee_id),
        "call": str(ticket.call_id),
        "account": str(ticket.account_id),
        "iat": now,
        "exp": now + TTL,
    }
    return jwt.encode(claims, jwt_secret(), algorithm="HS256")


def read(token: str) -> WebTicket | None:
    """The ticket, or None if it is forged, expired, or not a web-call ticket."""
    try:
        claims = jwt.decode(
            token, jwt_secret(), algorithms=["HS256"], options={"require": ["typ", "exp", "iat"]}
        )
        if claims["typ"] != TYPE:
            return None
        return WebTicket(
            employee_id=uuid.UUID(claims["employee"]),
            call_id=uuid.UUID(claims["call"]),
            account_id=uuid.UUID(claims["account"]),
        )
    except (jwt.InvalidTokenError, KeyError, ValueError):
        return None


OAUTH_TTL = timedelta(minutes=10)
OAUTH_TYPE = "sheets_oauth"


def issue_oauth_state(
    user_id: uuid.UUID, employee_id: uuid.UUID, now: datetime | None = None
) -> str:
    """The `state` of a Google consent link: signed, random, short-lived, and bound to the user and
    employee who asked for it, so a link crafted by someone else cannot be completed by them."""
    now = now or datetime.now(UTC)
    claims = {
        "typ": OAUTH_TYPE,
        "user": str(user_id),
        "employee": str(employee_id),
        "nonce": uuid.uuid4().hex,
        "iat": now,
        "exp": now + OAUTH_TTL,
    }
    return jwt.encode(claims, jwt_secret(), algorithm="HS256")


def read_oauth_state(token: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    """(user id, employee id) the state was issued for, or None if it is forged or expired."""
    try:
        claims = jwt.decode(
            token, jwt_secret(), algorithms=["HS256"], options={"require": ["typ", "exp", "iat"]}
        )
        if claims["typ"] != OAUTH_TYPE:
            return None
        return uuid.UUID(claims["user"]), uuid.UUID(claims["employee"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        return None


CALL_TYPE = "call_ticket"


def issue_call_ticket(
    kind: str, call_id: uuid.UUID, ttl: timedelta, now: datetime | None = None
) -> str:
    """A signed, short-lived pass that names one call and one purpose (`kind`), for a URL the
    carrier will fetch: it carries no login, so it can open nothing else."""
    now = now or datetime.now(UTC)
    claims = {"typ": CALL_TYPE, "kind": kind, "call": str(call_id), "iat": now, "exp": now + ttl}
    return jwt.encode(claims, jwt_secret(), algorithm="HS256")


def read_call_ticket(token: str, kind: str) -> uuid.UUID | None:
    """The call the ticket names, or None if it is forged, expired, or for another purpose."""
    try:
        claims = jwt.decode(
            token, jwt_secret(), algorithms=["HS256"], options={"require": ["typ", "exp", "iat"]}
        )
        if claims["typ"] != CALL_TYPE or claims["kind"] != kind:
            return None
        return uuid.UUID(claims["call"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        return None
