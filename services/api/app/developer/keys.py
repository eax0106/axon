"""API keys: made once, shown once, stored as a hash, checked on every public request.

A key is `axk_live_` and 43 random characters. Only its SHA-256 is kept (a random 256-bit secret
needs no slow hash), plus the first characters so the owner can tell keys apart.
"""

import hashlib
import logging
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, update

from app.db import Session
from app.models import ApiKey

log = logging.getLogger("axon.api")

PREFIX = "axk_live_"
SHOWN = len(PREFIX) + 6  # characters kept in the clear to recognise a key
MAX_ACTIVE_KEYS = 20
LIMIT_PER_MINUTE = 120
TOUCH_EVERY = timedelta(minutes=1)  # last_used_at is written at most this often per key

_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="ApiKey",
    description="Send your API key as `Authorization: Bearer axk_live_...`.",
)


def digest(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def new_key() -> tuple[str, str, str]:
    """The key itself (shown once), the part kept in the clear, and the hash that is stored."""
    key = PREFIX + secrets.token_urlsafe(32)
    return key, key[:SHOWN], digest(key)


@dataclass(frozen=True)
class ApiAuth:
    account_id: uuid.UUID
    key_id: uuid.UUID


def _refuse(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"}
    )


async def _within_limit(request: Request, key_id: uuid.UUID) -> None:
    """At most LIMIT_PER_MINUTE requests a minute per key. If Redis is down the API stays up."""
    minute = int(time.time() // 60)
    bucket = f"axon:api:{key_id}:{minute}"
    try:
        async with request.app.state.redis.pipeline() as pipe:
            pipe.incr(bucket)
            pipe.expire(bucket, 120)
            used = (await pipe.execute())[0]
    except Exception as exc:
        log.warning("rate limit unavailable: %s", type(exc).__name__)
        return
    if used > LIMIT_PER_MINUTE:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"limit of {LIMIT_PER_MINUTE} requests a minute for this key reached",
            headers={"Retry-After": str(60 - int(time.time()) % 60)},
        )


async def api_key(
    request: Request,
    session: Session,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> ApiAuth:
    token = credentials.credentials if credentials else ""
    row = None
    if token.startswith(PREFIX):
        row = await session.scalar(select(ApiKey).where(ApiKey.key_hash == digest(token)))
    if row is None or row.revoked_at is not None:
        raise _refuse("missing, unknown or revoked API key")
    auth = ApiAuth(row.account_id, row.id)
    request.state.api_auth = auth  # for the request log
    now = datetime.now(UTC)
    if row.last_used_at is None or row.last_used_at < now - TOUCH_EVERY:
        await session.execute(update(ApiKey).where(ApiKey.id == row.id).values(last_used_at=now))
        await session.commit()
    await _within_limit(request, row.id)
    return auth


Authenticated = Annotated[ApiAuth, Depends(api_key)]
