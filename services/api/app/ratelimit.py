"""Fixed-window limits on sign-in, sign-up and password-change attempts, counted in Redis.

A lock is keyed on the email text, whether or not the account exists, so it tells an attacker
nothing about who has an account. When Redis is down the attempt is answered anyway (the
readiness probe already reports Redis); `AXON_AUTH_RATE_LIMIT=off` turns the limits off for a
load test.
"""

import logging
import os

from fastapi import HTTPException, Request, status
from redis.exceptions import RedisError

log = logging.getLogger(__name__)

OFF_ENV = "AXON_AUTH_RATE_LIMIT"
WINDOW_S = 900
SIGNIN_PER_EMAIL = 10  # tries per email per window; a right password clears the count
SIGNIN_PER_ADDRESS = 100  # tries per address per window; an office behind one NAT shares it
SIGNUPS_PER_HOUR = 10
PASSWORD_PER_USER = 5  # password changes tried per user per window


def _enabled() -> bool:
    return os.environ.get(OFF_ENV, "").lower() != "off"


def client_address(request: Request) -> str:
    # Behind a proxy, uvicorn's FORWARDED_ALLOW_IPS decides whose X-Forwarded-For is believed.
    return request.client.host if request.client else "unknown"


def _too_many(retry_after: int) -> HTTPException:
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "too many attempts: try again later",
        headers={"Retry-After": str(retry_after)},
    )


async def hit(request: Request, key: str, limit: int, window_s: int = WINDOW_S) -> None:
    """Count one attempt on `key` and refuse with 429 once it is past `limit` in its window (which
    starts at the first attempt). Counting before the check keeps parallel guesses inside it."""
    if not _enabled():
        return
    try:
        async with request.app.state.redis.pipeline(transaction=True) as pipe:
            pipe.set(f"rl:{key}", 0, ex=window_s, nx=True)
            pipe.incr(f"rl:{key}")
            pipe.ttl(f"rl:{key}")
            _, count, ttl = await pipe.execute()
    except (RedisError, OSError):
        log.warning("rate limit skipped: redis unavailable")
        return
    if count > limit:
        raise _too_many(max(ttl, 1))


async def clear(request: Request, key: str) -> None:
    if not _enabled():
        return
    try:
        await request.app.state.redis.delete(f"rl:{key}")
    except (RedisError, OSError):
        log.warning("rate limit clear skipped: redis unavailable")
