"""Short-lived tickets for the browser test call.

The browser connects its audio WebSocket to the engine, which has no login. The API hands the
signed-in user a ticket (an HS256 token with its own `typ`, so it can never pass as a login
token and a login token can never open a call) that names one employee and one test-call row.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from app.auth import _secret

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
    return jwt.encode(claims, _secret(), algorithm="HS256")


def read(token: str) -> WebTicket | None:
    """The ticket, or None if it is forged, expired, or not a web-call ticket."""
    try:
        claims = jwt.decode(
            token, _secret(), algorithms=["HS256"], options={"require": ["typ", "exp", "iat"]}
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
