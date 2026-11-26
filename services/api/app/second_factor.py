"""The staff second factor: a TOTP authenticator app, plus one-time recovery codes.

Staff sign in with their password and get a five-minute challenge (app.auth.login). A staff
member who has not set up a second factor must do so then (`enrol`, then `confirm`), so the first
staff sign-in after this shipped enrols everyone; after that every sign-in needs a code
(`verify`). Only a session made here opens the admin console (app.auth.require_admin). A staff
member who lost the phone and the recovery codes is reset by another staff member
(app.admin.accounts), which is logged.

Owners and members may turn the same second factor on from Account settings (`/setup`, then
`/setup/confirm`, from a signed-in session); from then on their sign-in asks for a code too. They
turn it off with a current code (`/disable`). One who lost the phone and the recovery codes is
reset by ALTERX staff the same way (the reset turns it off), and that is logged. Developer API
keys are separate credentials and are not affected.
"""

import hashlib
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app import ratelimit, totp
from app.auth import OwnUser, issue_token, user_of_challenge
from app.db import Session
from app.models import AuditEntry, User

router = APIRouter(prefix="/auth/second-factor")
RECOVERY_CODES = 10
TRIES_PER_USER = 5  # codes tried per staff member per 15 minutes; a right one clears the count


class Challenge(BaseModel):
    challenge: str = Field(max_length=2000)


class CodeAnswer(Challenge):
    # Six digits from the app, or one recovery code (verify only).
    code: str = Field(min_length=6, max_length=40)


class Enrolment(BaseModel):
    secret: str  # base32, for typing into the app by hand
    otpauth_uri: str  # what the app's QR scanner reads


class Signed(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth2 token type, not a secret


class Enrolled(Signed):
    recovery_codes: list[str]  # shown this once; each works one time instead of a code


def _hash(code: str) -> str:
    clean = code.strip().replace("-", "").replace(" ", "").lower()
    return hashlib.sha256(clean.encode()).hexdigest()


def new_recovery_codes() -> tuple[list[str], list[str]]:
    """Codes to show (xxxxx-xxxxx, 50 random bits each) and the hashes to keep."""
    codes = []
    for _ in range(RECOVERY_CODES):
        raw = secrets.token_hex(5)
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes, [_hash(c) for c in codes]


def _audit(session: AsyncSession, user: User, action: str) -> None:
    session.add(
        AuditEntry(
            account_id=user.account_id,
            actor_user_id=user.id,
            action=action,
            target_type="user",
            target_id=str(user.id),
        )
    )


@router.post("/enrol")
async def enrol(body: Challenge, session: Session) -> Enrolment:
    """Start setting up the authenticator app. Asking again (a reload) answers the same unconfirmed
    seed, so the key on screen always matches the one kept."""
    user = await user_of_challenge(session, body.challenge)
    await session.refresh(user, with_for_update=True)
    if user.totp_enabled_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "a second factor is already set up")
    seed = user.totp_secret or totp.new_seed()
    user.totp_secret = seed
    await session.commit()
    return Enrolment(secret=seed, otpauth_uri=totp.otpauth_uri(seed, user.email))


async def _count_try(session: AsyncSession, request: Request, user: User) -> str:
    """Count one code tried, then lock the user's row: two requests with the same code cannot both
    pass the replay check or both spend one recovery code."""
    key = f"second-factor:{user.id}"
    # Fails closed: without a count, six-digit codes could be guessed without end.
    await ratelimit.hit(request, key, TRIES_PER_USER, fail_closed=True)
    await session.refresh(user, with_for_update=True)
    return key


def _wrong_code() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, "that code is not right")


@router.post("/confirm")
async def confirm(body: CodeAnswer, session: Session, request: Request) -> Enrolled:
    """Finish setting up: the first code from the app proves it holds the seed. Answers a session
    and the recovery codes."""
    user = await user_of_challenge(session, body.challenge)
    key = await _count_try(session, request, user)
    if user.totp_enabled_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "a second factor is already set up")
    if user.totp_secret is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "start the set-up first")
    now = datetime.now(UTC)
    step = totp.match(user.totp_secret, body.code, now.timestamp(), None)
    if step is None:
        raise _wrong_code()
    await ratelimit.clear(request, key)
    codes, hashes = new_recovery_codes()
    user.totp_enabled_at, user.totp_last_step, user.recovery_code_hashes = now, step, hashes
    _audit(session, user, "second_factor_enrolled")
    await session.commit()
    token = issue_token(user, second_factor=True)
    return Enrolled(access_token=token, recovery_codes=codes)


@router.post("/verify")
async def verify(body: CodeAnswer, session: Session, request: Request) -> Signed:
    """Sign in with a code from the app, or with one unused recovery code (then spent)."""
    user = await user_of_challenge(session, body.challenge)
    key = await _count_try(session, request, user)
    if user.totp_enabled_at is None or user.totp_secret is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "set up a second factor first")
    step = totp.match(
        user.totp_secret, body.code, datetime.now(UTC).timestamp(), user.totp_last_step
    )
    if step is not None:
        user.totp_last_step = step
    elif (hashed := _hash(body.code)) in user.recovery_code_hashes:
        user.recovery_code_hashes = [h for h in user.recovery_code_hashes if h != hashed]
        _audit(session, user, "recovery_code_used")
    else:
        raise _wrong_code()
    await ratelimit.clear(request, key)
    await session.commit()
    return Signed(access_token=issue_token(user, second_factor=True))


class Recovery(BaseModel):
    recovery_codes: list[str]  # shown this once; each works one time instead of a code


class Code(BaseModel):
    code: str = Field(min_length=6, max_length=40)


def _not_staff(user: User) -> None:
    if user.is_platform_admin:  # staff set theirs up at sign-in and cannot turn it off
        raise HTTPException(status.HTTP_409_CONFLICT, "staff second factors are set at sign-in")


@router.post("/setup")
async def setup(user: OwnUser, session: Session) -> Enrolment:
    """An owner or member starts turning on the authenticator app from a signed-in session. Asking
    again answers the same unconfirmed seed."""
    _not_staff(user)
    await session.refresh(user, with_for_update=True)
    if user.totp_enabled_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "a second factor is already set up")
    seed = user.totp_secret or totp.new_seed()
    user.totp_secret = seed
    await session.commit()
    return Enrolment(secret=seed, otpauth_uri=totp.otpauth_uri(seed, user.email))


@router.post("/setup/confirm")
async def setup_confirm(body: Code, user: OwnUser, session: Session, request: Request) -> Recovery:
    """Finish turning it on with the first code from the app. Answers the recovery codes; this
    session carries on, and every later sign-in asks for a code."""
    _not_staff(user)
    key = await _count_try(session, request, user)
    if user.totp_enabled_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "a second factor is already set up")
    if user.totp_secret is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "start the set-up first")
    now = datetime.now(UTC)
    step = totp.match(user.totp_secret, body.code, now.timestamp(), None)
    if step is None:
        raise _wrong_code()
    await ratelimit.clear(request, key)
    codes, hashes = new_recovery_codes()
    user.totp_enabled_at, user.totp_last_step, user.recovery_code_hashes = now, step, hashes
    _audit(session, user, "second_factor_enrolled")
    await session.commit()
    return Recovery(recovery_codes=codes)


@router.post("/disable", status_code=status.HTTP_204_NO_CONTENT)
async def disable(body: Code, user: OwnUser, session: Session, request: Request) -> None:
    """Turn the second factor off. Needs a current code from the app (not a recovery code), so a
    session left open on a shared computer cannot remove it."""
    _not_staff(user)
    key = await _count_try(session, request, user)
    if user.totp_enabled_at is None or user.totp_secret is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "no second factor is set up")
    if (
        totp.match(user.totp_secret, body.code, datetime.now(UTC).timestamp(), user.totp_last_step)
        is None
    ):
        raise _wrong_code()
    await ratelimit.clear(request, key)
    user.totp_secret = user.totp_enabled_at = user.totp_last_step = None
    user.recovery_code_hashes = []
    _audit(session, user, "second_factor_disabled")
    await session.commit()
