"""Own email/password auth: argon2 password hashes, HS256 JWT bearer tokens, account roles."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import ratelimit
from app.billing import ledger
from app.billing.config import free_signup_credits
from app.db import Session
from app.models import Account, AuditEntry, LedgerKind, Role, User
from app.settings import get_settings

TOKEN_TTL = timedelta(hours=12)
IMPERSONATION_TTL = timedelta(minutes=30)
# A staff member's password opens only this: five minutes to give the second factor.
CHALLENGE_TTL = timedelta(minutes=5)
CHALLENGE_AUDIENCE = "axon:second-factor"
MIN_SECRET_LEN = 32
# Hashing takes tens of milliseconds of CPU: callers run it in a thread (argon2 releases the GIL)
# so one sign-in never stalls every other request on the worker.
_hasher = PasswordHasher()
# Verified against when the email is unknown, so both paths cost one argon2 verify.
_DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-password")
_bearer = HTTPBearer(auto_error=False)

router = APIRouter()


class AuthNotConfiguredError(Exception):
    pass


def jwt_secret() -> str:
    secret = get_settings().jwt_secret
    if len(secret) < MIN_SECRET_LEN:
        raise AuthNotConfiguredError
    return secret


def issue_token(
    user: User,
    now: datetime | None = None,
    impersonator: User | None = None,
    second_factor: bool = False,
) -> str:
    """A session for `user`. With `impersonator` (platform staff) it is a short support session:
    every change made with it is logged under the staff member's id. `second_factor` marks a
    session signed in with a staff second factor; only such a session opens the admin console."""
    now = now or datetime.now(UTC)
    # `iat` keeps its fraction of a second, so a password change revokes every older session.
    claims: dict[str, object] = {
        "sub": str(user.id),
        "iat": now.timestamp(),
        "exp": now + TOKEN_TTL,
    }
    if impersonator is not None:
        claims["imp"], claims["exp"] = str(impersonator.id), now + IMPERSONATION_TTL
    if second_factor:
        claims["mfa"] = True
    return jwt.encode(claims, jwt_secret(), algorithm="HS256")


def issue_challenge(user: User, now: datetime | None = None) -> str:
    """Proof that `user` gave the right password, good only for the second-factor routes (its
    audience makes every other route refuse it)."""
    now = now or datetime.now(UTC)
    claims = {
        "sub": str(user.id),
        "aud": CHALLENGE_AUDIENCE,
        "iat": now.timestamp(),
        "exp": now + CHALLENGE_TTL,
    }
    return jwt.encode(claims, jwt_secret(), algorithm="HS256")


async def user_of_challenge(session: AsyncSession, challenge: str) -> User:
    """The staff member a challenge was issued to. Refused once it expires, after a password
    change or a second-factor reset, or when the user is no longer staff."""
    try:
        claims = jwt.decode(
            challenge,
            jwt_secret(),
            algorithms=["HS256"],
            audience=CHALLENGE_AUDIENCE,
            options={"require": ["sub", "exp", "iat", "aud"]},
        )
        user_id = uuid.UUID(claims["sub"])
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise _unauthorized("sign in again") from exc
    user = await session.get(User, user_id)
    if user is None or not user.is_platform_admin or _revoked(user, claims["iat"]):
        raise _unauthorized("sign in again")
    return user


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"}
    )


async def current_user(
    request: Request,
    session: Session,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise _unauthorized("not authenticated")
    user, impersonator, second_factor = await _session_of(session, credentials.credentials)
    request.state.impersonator = impersonator
    request.state.second_factor = second_factor
    if impersonator is not None and request.method not in ("GET", "HEAD", "OPTIONS"):
        # Written before the change, in its own transaction: the attempt is logged even if the
        # change itself fails.
        session.add(
            AuditEntry(
                account_id=user.account_id,
                actor_user_id=user.id,
                impersonator_user_id=impersonator,
                action="impersonated_request",
                target_type="route",
                target_id=f"{request.method} {request.url.path}"[:100],
            )
        )
        await session.commit()
    return user


async def user_from_token(session: AsyncSession, token: str) -> User:
    return (await _session_of(session, token))[0]


async def _session_of(session: AsyncSession, token: str) -> tuple[User, uuid.UUID | None, bool]:
    """The user a token speaks for, the staff member impersonating them (if any), and whether it
    was signed in with a second factor. Refused when the token was issued before the user's last
    password change, or when the impersonator is no longer platform staff."""
    try:
        claims = jwt.decode(
            token,
            jwt_secret(),
            algorithms=["HS256"],
            options={"require": ["sub", "exp", "iat"]},
        )
        user_id = uuid.UUID(claims["sub"])
        impersonator_id = uuid.UUID(claims["imp"]) if "imp" in claims else None
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise _unauthorized("invalid or expired token") from exc
    user = await session.get(User, user_id)
    if user is None or _revoked(user, claims["iat"]):
        raise _unauthorized("invalid or expired token")
    if impersonator_id is not None:
        staff = await session.get(User, impersonator_id)
        if staff is None or not staff.is_platform_admin:
            raise _unauthorized("invalid or expired token")
    return user, impersonator_id, claims.get("mfa") is True


def _revoked(user: User, issued_at: float) -> bool:
    valid_after = user.tokens_valid_after
    return valid_after is not None and issued_at < valid_after.timestamp()


CurrentUser = Annotated[User, Depends(current_user)]


async def require_admin(user: CurrentUser, request: Request) -> User:
    """Platform staff only; account roles never grant this, and neither does a support session.
    The session must have been signed in with the staff second factor: one from before it was
    required, or from before the user became staff, is sent back to sign in."""
    if not user.is_platform_admin or request.state.impersonator is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "platform admins only")
    if not request.state.second_factor:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "sign in again with your second factor to use the console"
        )
    return user


def refuse_in_support_session(request: Request) -> None:
    """For what only the account's own people may do: change the password, and anything that
    outlives a support session and lets calls be placed or sends the account's calls or data out
    (API keys, the lead-intake secret, webhooks and their signing secrets, actions, a Google, Meta
    or Sheets connection, a transfer number), or that spends the account's money or speaks for
    who it is (numbers, KYC, top-ups, the owner's verified phone).
    Routes that also take other changes call it only when such a field changes."""
    if request.state.impersonator is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not allowed in a support session")


async def not_impersonating(user: CurrentUser, request: Request) -> User:
    refuse_in_support_session(request)
    return user


OwnUser = Annotated[User, Depends(not_impersonating)]


class Credentials(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        value = value.strip().lower()
        local, _, domain = value.partition("@")
        if not local or "." not in domain or " " in value:
            raise ValueError("not an email address")
        return value


class Signup(Credentials):
    account_name: str = Field(min_length=1, max_length=200)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth2 token type, not a secret


class SignIn(BaseModel):
    """A session, or for staff a challenge: send it with a code to /auth/second-factor/verify, or
    (`enrol`, the first sign-in after the second factor became required) set one up first."""

    access_token: str | None = None
    token_type: str = "bearer"  # noqa: S105 - OAuth2 token type, not a secret
    second_factor: Literal["verify", "enrol"] | None = None
    challenge: str | None = None


@router.post("/auth/signup", status_code=status.HTTP_201_CREATED)
async def signup(body: Signup, session: Session, request: Request) -> Token:
    jwt_secret()  # fail with 503 before creating anything if tokens can't be issued
    key = f"signup:{ratelimit.client_address(request)}"
    await ratelimit.hit(request, key, ratelimit.SIGNUPS_PER_HOUR, window_s=3600)
    account = Account(name=body.account_name)
    session.add(account)
    await session.flush()
    await ledger.post(
        session, account.id, LedgerKind.BONUS, free_signup_credits(),
        ref_type="signup", ref_id=str(account.id), note="free credits",
    )  # fmt: skip
    user = User(
        account_id=account.id,
        email=body.email,
        password_hash=await asyncio.to_thread(_hasher.hash, body.password),
        role=Role.OWNER,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered") from exc
    return Token(access_token=issue_token(user))


@router.post("/auth/login")
async def login(body: Credentials, session: Session, request: Request) -> SignIn:
    jwt_secret()
    by_address = f"login:address:{ratelimit.client_address(request)}"
    by_email = f"login:email:{body.email}"
    await ratelimit.hit(request, by_address, ratelimit.SIGNIN_PER_ADDRESS)
    await ratelimit.hit(request, by_email, ratelimit.SIGNIN_PER_EMAIL)
    user = await session.scalar(select(User).where(func.lower(User.email) == body.email))
    try:
        await asyncio.to_thread(
            _hasher.verify, user.password_hash if user else _DUMMY_HASH, body.password
        )
    except VerificationError:
        user = None
    if user is None:
        raise _unauthorized("invalid email or password")
    await ratelimit.clear(request, by_email)
    if _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = await asyncio.to_thread(_hasher.hash, body.password)
        await session.commit()
    if user.is_platform_admin:
        enrolled = user.totp_enabled_at is not None
        return SignIn(
            second_factor="verify" if enrolled else "enrol", challenge=issue_challenge(user)
        )
    return SignIn(access_token=issue_token(user))


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/auth/password")
async def change_password(
    body: PasswordChange, user: OwnUser, session: Session, request: Request
) -> Token:
    """Change the password. Every session issued before it is signed out, on every device; the
    answer is a fresh session for this one."""
    key = f"password:{user.id}"
    await ratelimit.hit(request, key, ratelimit.PASSWORD_PER_USER)
    try:
        await asyncio.to_thread(_hasher.verify, user.password_hash, body.current_password)
    except VerificationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "current password is wrong") from exc
    await ratelimit.clear(request, key)
    now = datetime.now(UTC)
    user.password_hash = await asyncio.to_thread(_hasher.hash, body.new_password)
    user.tokens_valid_after = now
    session.add(AuditEntry(account_id=user.account_id, actor_user_id=user.id, action="password"))
    await session.commit()
    second_factor = request.state.second_factor
    return Token(access_token=issue_token(user, now, second_factor=second_factor))


@router.get("/accounts/me")
async def me(
    user: CurrentUser, session: Session, request: Request
) -> dict[str, dict[str, str | bool]]:
    account = await session.get(Account, user.account_id)
    assert account is not None  # FK guarantees it
    return {
        "user": {
            "id": str(user.id),
            "email": user.email,
            "role": user.role.value,
            # Staff see the admin console; a support session (staff acting as this user) never does.
            "staff": user.is_platform_admin,
            # Whether this session was signed in with the staff second factor (opens the console).
            "second_factor": bool(request.state.second_factor),
            "support_session": request.state.impersonator is not None,
        },
        # The verified owner phone ("" until verified): free test calls ring only this number.
        "account": {
            "id": str(account.id),
            "name": account.name,
            "owner_phone": account.owner_phone or "",
        },
    }
