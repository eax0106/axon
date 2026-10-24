"""Own email/password auth: argon2 password hashes, HS256 JWT bearer tokens, account roles."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db import Session
from app.models import Account, Role, User
from app.settings import get_settings

TOKEN_TTL = timedelta(hours=12)
MIN_SECRET_LEN = 32
_hasher = PasswordHasher()
# Verified against when the email is unknown, so both paths cost one argon2 verify.
_DUMMY_HASH = _hasher.hash("timing-equaliser-not-a-password")
_bearer = HTTPBearer(auto_error=False)

router = APIRouter()


class AuthNotConfiguredError(Exception):
    pass


def _secret() -> str:
    secret = get_settings().jwt_secret
    if len(secret) < MIN_SECRET_LEN:
        raise AuthNotConfiguredError
    return secret


def issue_token(user: User, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    claims = {"sub": str(user.id), "iat": now, "exp": now + TOKEN_TTL}
    return jwt.encode(claims, _secret(), algorithm="HS256")


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"}
    )


async def current_user(
    session: Session,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None:
        raise _unauthorized("not authenticated")
    try:
        claims = jwt.decode(
            credentials.credentials,
            _secret(),
            algorithms=["HS256"],
            options={"require": ["sub", "exp", "iat"]},
        )
        user_id = uuid.UUID(claims["sub"])
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise _unauthorized("invalid or expired token") from exc
    user = await session.get(User, user_id)
    if user is None:
        raise _unauthorized("invalid or expired token")
    return user


CurrentUser = Annotated[User, Depends(current_user)]


async def require_admin(user: CurrentUser) -> User:
    """Platform staff only; account roles never grant this."""
    if not user.is_platform_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "platform admins only")
    return user


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


@router.post("/auth/signup", status_code=status.HTTP_201_CREATED)
async def signup(body: Signup, session: Session) -> Token:
    _secret()  # fail with 503 before creating anything if tokens can't be issued
    account = Account(name=body.account_name)
    session.add(account)
    await session.flush()
    user = User(
        account_id=account.id,
        email=body.email,
        password_hash=_hasher.hash(body.password),
        role=Role.OWNER,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "email already registered") from exc
    return Token(access_token=issue_token(user))


@router.post("/auth/login")
async def login(body: Credentials, session: Session) -> Token:
    _secret()
    user = await session.scalar(select(User).where(func.lower(User.email) == body.email))
    try:
        _hasher.verify(user.password_hash if user else _DUMMY_HASH, body.password)
    except VerificationError:
        user = None
    if user is None:
        raise _unauthorized("invalid email or password")
    if _hasher.check_needs_rehash(user.password_hash):
        user.password_hash = _hasher.hash(body.password)
        await session.commit()
    return Token(access_token=issue_token(user))


@router.get("/accounts/me")
async def me(user: CurrentUser, session: Session) -> dict[str, dict[str, str]]:
    account = await session.get(Account, user.account_id)
    assert account is not None  # FK guarantees it
    return {
        "user": {"id": str(user.id), "email": user.email, "role": user.role.value},
        "account": {"id": str(account.id), "name": account.name},
    }
