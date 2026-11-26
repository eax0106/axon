"""The account's team: email invites for members, removing them, and password resets.

Both kinds of link carry a 32-byte random token; only its SHA-256 is stored, and it works once.
An invite lasts 7 days and makes a `member` (calls, leads and campaigns; never billing, numbers,
API keys or account settings, which are owner-only). A reset lasts 1 hour and signs out every
session. Links open the dashboard with the token after `#`, so it never reaches a server log.
Email goes through the email provider; without it (or without AXON_APP_PUBLIC_URL) these routes
answer 503 provider_not_configured before anything is stored. Every change is in the audit log.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import ratelimit
from app.auth import Token, clean_email, hash_password, issue_token, refuse_in_support_session
from app.db import Session
from app.employees.router import OwnerUser
from app.models import Account, AuditEntry, EmailToken, Role, User
from app.providers.base import EmailProvider, ProviderKind
from app.providers.registry import require
from app.settings import app_public_url

router = APIRouter()
INVITE = "invite"
RESET = "password_reset"
INVITE_TTL = timedelta(days=7)
RESET_TTL = timedelta(hours=1)
INVITES_PER_HOUR = 20  # per account
RESETS_PER_EMAIL = 3  # reset emails per address per 15 minutes
TOKEN_TRIES_PER_ADDRESS = 30  # links tried per client address per 15 minutes


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _email_provider() -> EmailProvider:
    provider = require(ProviderKind.EMAIL)
    assert isinstance(provider, EmailProvider)
    return provider


def _audit(
    session: AsyncSession, actor: User | None, account_id: uuid.UUID, action: str, target: str
) -> None:
    session.add(
        AuditEntry(
            account_id=account_id,
            actor_user_id=actor.id if actor else None,
            action=action,
            target_type="user",
            target_id=target[:100],
        )
    )


def _issue(
    session: AsyncSession, purpose: str, account_id: uuid.UUID, email: str, **fields: object
) -> str:
    token = secrets.token_urlsafe(32)
    ttl = INVITE_TTL if purpose == INVITE else RESET_TTL
    session.add(
        EmailToken(
            account_id=account_id,
            purpose=purpose,
            email=email,
            token_hash=_hash(token),
            expires_at=datetime.now(UTC) + ttl,
            **fields,
        )
    )
    return token


async def _redeem(session: AsyncSession, request: Request, purpose: str, token: str) -> EmailToken:
    """The token's row, locked, if it is unused, unrevoked and unexpired; else 410."""
    await ratelimit.hit(
        request, f"email-token:{ratelimit.client_address(request)}", TOKEN_TRIES_PER_ADDRESS
    )
    row = await session.scalar(
        select(EmailToken)
        .where(EmailToken.token_hash == _hash(token), EmailToken.purpose == purpose)
        .with_for_update()
    )
    if (
        row is None
        or row.used_at is not None
        or row.revoked_at is not None
        or row.expires_at <= datetime.now(UTC)
    ):
        raise HTTPException(status.HTTP_410_GONE, "this link was used, cancelled or has expired")
    return row


# --- The owner's team page -------------------------------------------------------------------


class Member(BaseModel):
    id: uuid.UUID
    email: str
    role: Role
    two_factor: bool
    joined_at: datetime


class PendingInvite(BaseModel):
    id: uuid.UUID
    email: str
    expires_at: datetime
    sent_at: datetime


class Team(BaseModel):
    members: list[Member]
    invites: list[PendingInvite]


class InviteIn(BaseModel):
    email: str = Field(max_length=320)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        return clean_email(value)


@router.get("/team")
async def team(user: OwnerUser, session: Session) -> Team:
    users = await session.scalars(
        select(User).where(User.account_id == user.account_id).order_by(User.created_at)
    )
    invites = await session.scalars(
        select(EmailToken)
        .where(
            EmailToken.account_id == user.account_id,
            EmailToken.purpose == INVITE,
            EmailToken.used_at.is_(None),
            EmailToken.revoked_at.is_(None),
            EmailToken.expires_at > func.now(),
        )
        .order_by(EmailToken.created_at.desc())
    )
    return Team(
        members=[
            Member(
                id=u.id,
                email=u.email,
                role=u.role,
                two_factor=u.totp_enabled_at is not None,
                joined_at=u.created_at,
            )
            for u in users
        ],
        invites=[
            PendingInvite(id=i.id, email=i.email, expires_at=i.expires_at, sent_at=i.created_at)
            for i in invites
        ],
    )


@router.post("/team/invites", status_code=status.HTTP_201_CREATED)
async def invite(
    body: InviteIn, user: OwnerUser, session: Session, request: Request
) -> PendingInvite:
    """Email a link that lets `email` join this account as a member. Asking again for the same
    email cancels the earlier link. Refused for an email that already has an Axon sign-in."""
    refuse_in_support_session(request)
    provider, link_base = _email_provider(), app_public_url()  # 503 before anything is stored
    await ratelimit.hit(request, f"invites:{user.account_id}", INVITES_PER_HOUR, window_s=3600)
    taken = await session.scalar(select(User.id).where(func.lower(User.email) == body.email))
    if taken is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "this email already has an Axon sign-in")
    now = datetime.now(UTC)
    await session.execute(
        update(EmailToken)
        .where(
            EmailToken.account_id == user.account_id,
            EmailToken.purpose == INVITE,
            EmailToken.email == body.email,
            EmailToken.used_at.is_(None),
            EmailToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    token = _issue(session, INVITE, user.account_id, body.email, invited_by=user.id)
    account = await session.get(Account, user.account_id)
    assert account is not None
    await provider.send(
        body.email,
        f"Join {account.name} on Axon",
        f"{user.email} invited you to join {account.name} on Axon.\n\n"
        f"Set your password and sign in here (the link works once, for 7 days):\n"
        f"{link_base}/join#{token}\n\n"
        "If you did not expect this, ignore this email.",
    )
    _audit(session, user, user.account_id, "invite_sent", body.email)
    await session.commit()
    row = await session.scalar(select(EmailToken).where(EmailToken.token_hash == _hash(token)))
    assert row is not None
    return PendingInvite(
        id=row.id, email=row.email, expires_at=row.expires_at, sent_at=row.created_at
    )


@router.delete("/team/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke(invite_id: uuid.UUID, user: OwnerUser, session: Session, request: Request) -> None:
    refuse_in_support_session(request)
    row = await session.get(EmailToken, invite_id, with_for_update=True)
    if row is None or row.account_id != user.account_id or row.purpose != INVITE:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such invite")
    if row.used_at is None and row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        _audit(session, user, user.account_id, "invite_revoked", row.email)
        await session.commit()


@router.delete("/team/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove(user_id: uuid.UUID, user: OwnerUser, session: Session, request: Request) -> None:
    """Remove a member. Their sign-in is deleted, so every session of theirs stops at once; what
    they wrote (notes, audit entries) stays, without their name."""
    refuse_in_support_session(request)
    member = await session.get(User, user_id, with_for_update=True)
    if member is None or member.account_id != user.account_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such member")
    if member.role is not Role.MEMBER or member.is_platform_admin:
        raise HTTPException(status.HTTP_409_CONFLICT, "only members can be removed")
    _audit(session, user, user.account_id, "member_removed", member.email)
    await session.execute(delete(User).where(User.id == member.id))
    await session.commit()


# --- Opening a link (signed out) --------------------------------------------------------------


class LinkIn(BaseModel):
    token: str = Field(min_length=20, max_length=100)


class InviteInfo(BaseModel):
    email: str
    account_name: str


class Accept(LinkIn):
    password: str = Field(min_length=8, max_length=128)


@router.post("/auth/invites/check")
async def check_invite(body: LinkIn, session: Session, request: Request) -> InviteInfo:
    """Who an invite link is for, to show before the password is chosen. Uses nothing up."""
    row = await _redeem(session, request, INVITE, body.token)
    account = await session.get(Account, row.account_id)
    assert account is not None
    info = InviteInfo(email=row.email, account_name=account.name)
    await session.rollback()  # release the lock
    return info


@router.post("/auth/invites/accept", status_code=status.HTTP_201_CREATED)
async def accept_invite(body: Accept, session: Session, request: Request) -> Token:
    """Join the account as a member with a new password; answers a session."""
    row = await _redeem(session, request, INVITE, body.token)
    if await session.scalar(select(User.id).where(func.lower(User.email) == row.email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "this email already has an Axon sign-in")
    member = User(
        account_id=row.account_id,
        email=row.email,
        password_hash=await hash_password(body.password),
        role=Role.MEMBER,
    )
    session.add(member)
    row.used_at = datetime.now(UTC)
    try:
        await session.flush()
    except IntegrityError as exc:  # the same email signed up a moment ago
        raise HTTPException(
            status.HTTP_409_CONFLICT, "this email already has an Axon sign-in"
        ) from exc
    _audit(session, member, row.account_id, "invite_accepted", row.email)
    await session.commit()
    return Token(access_token=issue_token(member))


class ResetRequest(BaseModel):
    email: str = Field(max_length=320)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        return clean_email(value)


class ResetConfirm(LinkIn):
    password: str = Field(min_length=8, max_length=128)


@router.post("/auth/password-reset", status_code=status.HTTP_202_ACCEPTED)
async def request_reset(
    body: ResetRequest, session: Session, request: Request
) -> dict[str, Literal["sent"]]:
    """Email a reset link if `email` has a sign-in. The answer is the same either way, so it does
    not tell who has one."""
    provider, link_base = _email_provider(), app_public_url()
    await ratelimit.hit(
        request, f"reset:address:{ratelimit.client_address(request)}", TOKEN_TRIES_PER_ADDRESS
    )
    await ratelimit.hit(request, f"reset:email:{body.email}", RESETS_PER_EMAIL)
    user = await session.scalar(select(User).where(func.lower(User.email) == body.email))
    if user is not None:
        token = _issue(session, RESET, user.account_id, user.email, user_id=user.id)
        await provider.send(
            user.email,
            "Reset your Axon password",
            "Someone asked to reset the password of this Axon sign-in.\n\n"
            f"Choose a new password here (the link works once, for 1 hour):\n"
            f"{link_base}/reset-password#{token}\n\n"
            "If it was not you, ignore this email: your password stays as it is.",
        )
        _audit(session, None, user.account_id, "password_reset_requested", user.email)
        await session.commit()
    return {"status": "sent"}


@router.post("/auth/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_reset(body: ResetConfirm, session: Session, request: Request) -> None:
    """Set the new password. Every session is signed out and every other reset link stops
    working; sign in again (with the second factor, if it is on)."""
    row = await _redeem(session, request, RESET, body.token)
    user = await session.get(User, row.user_id, with_for_update=True) if row.user_id else None
    if user is None:
        raise HTTPException(status.HTTP_410_GONE, "this link was used, cancelled or has expired")
    now = datetime.now(UTC)
    user.password_hash = await hash_password(body.password)
    user.tokens_valid_after = now
    await session.execute(
        update(EmailToken)
        .where(
            EmailToken.user_id == user.id, EmailToken.purpose == RESET, EmailToken.used_at.is_(None)
        )
        .values(used_at=now)
    )
    _audit(session, user, user.account_id, "password_reset", user.email)
    await session.commit()
