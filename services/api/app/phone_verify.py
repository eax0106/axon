"""Prove the owner holds their phone: a code spoken to it in a call.

Free test calls only ring the owner's own verified phone, so nobody can use them to ring other
people. The code is never stored or sent in a URL: it is derived from the one-time token (HMAC
under the server secret) when the carrier asks for what to say, and only its hash is kept to
check the answer against.
"""

import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from xml.sax.saxutils import escape

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, StringConstraints
from sqlalchemy import delete, select

from app.auth import CurrentUser, jwt_secret
from app.db import Session
from app.employees.limits import take
from app.employees.router import OwnerUser
from app.models import Account, DncEntry, NumberStatus, PhoneNumber, PhoneOtp
from app.numbers import channels
from app.providers.base import ProviderKind, TelephonyProvider
from app.providers.registry import require
from app.settings import api_public_url

router = APIRouter()
TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5
CALLS_PER_HOUR = 3
INDIAN_MOBILE = re.compile(r"^\+91[6-9]\d{9}$")


def code_for(token: str) -> str:
    digest = hmac.new(jwt_secret().encode(), token.encode(), hashlib.sha256).digest()
    return f"{int.from_bytes(digest[:8], 'big') % 1_000_000:06d}"


def _hash(code: str, token: str) -> str:
    return hashlib.sha256(f"{token}:{code}".encode()).hexdigest()


class PhoneBody(BaseModel):
    phone: Annotated[str, StringConstraints(pattern=INDIAN_MOBILE.pattern)]


@router.post("/accounts/owner-phone", status_code=status.HTTP_202_ACCEPTED)
async def send_code(body: PhoneBody, user: OwnerUser, session: Session) -> dict[str, int]:
    """Ring `phone` and read out a six-digit code."""
    telephony = require(ProviderKind.TELEPHONY)
    assert isinstance(telephony, TelephonyProvider)
    base = api_public_url()
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


@router.post("/accounts/owner-phone/verify")
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
    await session.execute(delete(PhoneOtp).where(PhoneOtp.account_id == user.account_id))
    await session.commit()
    return {"owner_phone": account.owner_phone}


@router.api_route("/public/otp/{token}", methods=["GET", "POST"])
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
