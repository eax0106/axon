"""Prove the owner holds their phone: a code spoken to it in a call.

Free test calls only ring the owner's own verified phone, so nobody can use them to ring other
people. The code is never stored or sent in a URL: it is derived from the one-time token (HMAC
under the server secret) when the carrier asks for what to say, and only its hash is kept to
check the answer against.
"""

import hashlib
import hmac
import os
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, StringConstraints
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser, jwt_secret, not_impersonating
from app.billing import ledger
from app.billing.config import free_signup_credits
from app.db import Session
from app.employees.limits import take
from app.employees.router import OwnerUser
from app.models import (
    Account,
    DncEntry,
    LedgerKind,
    NumberStatus,
    PhoneNumber,
    PhoneOtp,
    User,
)
from app.numbers import channels
from app.providers.base import ProviderKind, TelephonyProvider
from app.providers.registry import require
from app.settings import api_public_url

router = APIRouter()
TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5
CALLS_PER_HOUR = 3
CODES_PER_PHONE_PER_HOUR = 3  # across all accounts: the shared number must not ring anyone at will
# ALTERX's own number for code calls, so a new owner proves their phone (and gets the free
# credits) before buying a number. Unset: the code is spoken from one of the owner's numbers.
VERIFY_FROM_ENV = "AXON_VERIFY_FROM_NUMBER"
INDIAN_MOBILE = re.compile(r"^\+91[6-9]\d{9}$")


def code_for(token: str) -> str:
    digest = hmac.new(jwt_secret().encode(), token.encode(), hashlib.sha256).digest()
    return f"{int.from_bytes(digest[:8], 'big') % 1_000_000:06d}"


def _hash(code: str, token: str) -> str:
    return hashlib.sha256(f"{token}:{code}".encode()).hexdigest()


class PhoneBody(BaseModel):
    phone: Annotated[str, StringConstraints(pattern=INDIAN_MOBILE.pattern)]


async def _owner_number(session: AsyncSession, user: User) -> str:
    """One of the owner's own numbers with a free channel, to speak the code from."""
    held = await session.scalars(
        select(PhoneNumber)
        .where(PhoneNumber.account_id == user.account_id, PhoneNumber.status == NumberStatus.ACTIVE)
        .order_by(PhoneNumber.created_at)
    )
    numbers = list(held)
    if not numbers:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "buy a phone number first: the code is spoken from it"
        )
    from_number = None
    for candidate in numbers:
        if await channels.has_free_channel(session, candidate):
            from_number = candidate.e164
            break
    if from_number is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "every channel of your numbers is on a call: try again in a moment",
        )
    return from_number


@router.post(
    "/accounts/owner-phone",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(not_impersonating)],
)
async def send_code(body: PhoneBody, user: OwnerUser, session: Session) -> dict[str, int]:
    """Ring `phone` and read out a six-digit code."""
    telephony = require(ProviderKind.TELEPHONY)
    assert isinstance(telephony, TelephonyProvider)
    base = api_public_url()
    from_number = os.environ.get(VERIFY_FROM_ENV, "").strip() or await _owner_number(session, user)
    on_dnc = await session.scalar(
        select(DncEntry.id).where(
            DncEntry.account_id == user.account_id, DncEntry.phone == body.phone
        )
    )
    if on_dnc:  # the one outbound call here must honour the list like any other
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "that number is on the do-not-call list: remove it there before verifying it",
        )
    since = datetime.now(UTC) - timedelta(hours=1)
    rung = await session.scalar(
        select(func.count())
        .select_from(PhoneOtp)
        .where(PhoneOtp.phone == body.phone, PhoneOtp.created_at > since)
    )
    if (rung or 0) >= CODES_PER_PHONE_PER_HOUR:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "too many codes sent to this phone: try in an hour"
        )
    await take(session, user, "owner_phone_code", CALLS_PER_HOUR)
    token = secrets.token_urlsafe(32)
    session.add(
        PhoneOtp(
            account_id=user.account_id,
            phone=body.phone,
            token=token,
            code_hash=_hash(code_for(token), token),
            expires_at=datetime.now(UTC) + TTL,
        )
    )
    await session.commit()
    await telephony.originate(from_number, body.phone, f"{base}/public/otp/{token}")
    return {"expires_in": int(TTL.total_seconds())}


class CodeBody(BaseModel):
    code: Annotated[str, StringConstraints(pattern=r"^\d{6}$")]


@router.post("/accounts/owner-phone/verify", dependencies=[Depends(not_impersonating)])
async def verify_code(body: CodeBody, user: CurrentUser, session: Session) -> dict[str, str]:
    otp = await session.scalar(
        select(PhoneOtp)
        .where(PhoneOtp.account_id == user.account_id, PhoneOtp.expires_at > datetime.now(UTC))
        .order_by(PhoneOtp.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if otp is None or otp.attempts >= MAX_ATTEMPTS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "ask for a new code")
    if not hmac.compare_digest(otp.code_hash, _hash(body.code, otp.token)):
        otp.attempts += 1
        await session.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "that code is not right")
    account = await session.get(Account, user.account_id)
    assert account is not None  # FK guarantees it
    account.owner_phone, account.owner_phone_verified_at = otp.phone, datetime.now(UTC)
    # The free credits wait for a phone proven real, so made-up sign-ups cannot farm them: once
    # per account (the reference sign-up used to post under) and once per phone (no other account
    # proved it first). ponytail: two accounts proving one phone at the same instant could both
    # get them; a unique index on verified phones closes that if it is ever seen.
    claimed = await session.scalar(
        select(Account.id)
        .where(
            Account.owner_phone == otp.phone,
            Account.owner_phone_verified_at.is_not(None),
            Account.id != account.id,
        )
        .limit(1)
    )
    if claimed is None:
        await ledger.post(
            session, account.id, LedgerKind.BONUS, free_signup_credits(),
            ref_type="signup", ref_id=str(account.id), note="free credits",
        )  # fmt: skip
    await session.execute(delete(PhoneOtp).where(PhoneOtp.account_id == user.account_id))
    await session.commit()
    return {"owner_phone": account.owner_phone}


# Two decorators, not api_route(methods=[...]): that gives both methods one operation id.
@router.get("/public/otp/{token}", operation_id="speak_code_get")
@router.post("/public/otp/{token}", operation_id="speak_code_post")
async def speak_code(token: str, session: Session) -> Response:
    """What the carrier asks for when the owner picks up: read the code twice."""
    otp = await session.scalar(
        select(PhoneOtp).where(PhoneOtp.token == token, PhoneOtp.expires_at > datetime.now(UTC))
    )
    if otp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such code")
    digits = " ".join(code_for(token))
    text = escape(f"Your Axon verification code is {digits}. Again, {digits}. Goodbye.")
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<Response><Speak language="en-IN">{text}</Speak></Response>'
    )
    return Response(xml, media_type="application/xml")
