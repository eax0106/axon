"""The number store, the holder's KYC, and which employee uses which number."""

import re
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field, StringConstraints, field_validator
from sqlalchemy import select

from app.auth import CurrentUser
from app.billing import ledger
from app.billing.config import number_monthly_fee, number_setup_fee
from app.db import Session
from app.employees.router import OwnerUser, load
from app.models import (
    Employee,
    KycHolder,
    LedgerKind,
    NumberStatus,
    NumberType,
    PhoneNumber,
)
from app.numbers import attach as attaching
from app.numbers.renewals import next_month, today_ist
from app.providers.base import (
    InventoryNumber,
    NumberKycProvider,
    NumberStore,
    ProviderKind,
)
from app.providers.registry import require

router = APIRouter()
PAN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
VERIFIED = "verified"
PAN_VERIFIED = "pan_verified"


def _store() -> NumberStore:
    provider = require(ProviderKind.TELEPHONY)
    if not isinstance(provider, NumberStore):
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "this carrier sells no numbers")
    return provider


def _kyc() -> NumberKycProvider:
    provider = require(ProviderKind.NUMBER_KYC)
    assert isinstance(provider, NumberKycProvider)
    return provider


def _number_out(number: PhoneNumber, employee_id: uuid.UUID | None = None) -> dict[str, Any]:
    return {
        "id": number.id,
        "e164": number.e164,
        "number_type": number.number_type,
        "status": number.status,
        "channels": number.channels,
        "monthly_fee": str(ledger.credits(number.monthly_fee)),
        "renews_on": number.renews_on,
        "grace_until": number.grace_until,
        "employee_id": employee_id,
    }


@router.get("/numbers")
async def list_numbers(user: CurrentUser, session: Session) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(PhoneNumber, Employee.id)
        .outerjoin(Employee, Employee.number_id == PhoneNumber.id)
        .where(
            PhoneNumber.account_id == user.account_id, PhoneNumber.status != NumberStatus.RELEASED
        )
        .order_by(PhoneNumber.created_at)
    )
    return [_number_out(number, employee_id) for number, employee_id in rows]


# --- Store -----------------------------------------------------------------------------------


def _offer(item: InventoryNumber) -> dict[str, Any]:
    return {
        "e164": item.e164,
        "number_type": item.number_type,
        "setup_fee": str(number_setup_fee()),
        "monthly_fee": str(number_monthly_fee()),
    }


@router.get("/numbers/inventory")
async def inventory(
    user: CurrentUser,
    search: Annotated[str, Query(max_length=20, pattern=r"^\+?\d*$")] = "",
    page: Annotated[int, Query(ge=1)] = 1,
    per_page: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[dict[str, Any]]:
    """Numbers on sale at our price (not the carrier's)."""
    return [_offer(item) for item in await _store().search_numbers(search, page, per_page)]


async def _find(e164: str) -> InventoryNumber:
    for item in await _store().search_numbers(e164, 1, 100):
        if item.e164 == e164:
            return item
    raise HTTPException(status.HTTP_404_NOT_FOUND, "that number is not on sale")


async def _verified_holder(
    session: Session, account_id: uuid.UUID, holder_id: uuid.UUID | None
) -> KycHolder | None:
    query = select(KycHolder).where(
        KycHolder.account_id == account_id, KycHolder.status == VERIFIED
    )
    if holder_id is not None:
        query = query.where(KycHolder.id == holder_id)
    return await session.scalar(query.order_by(KycHolder.created_at.desc()).limit(1))


@router.get("/numbers/quote")
async def quote(
    user: CurrentUser,
    session: Session,
    e164: Annotated[str, Query(pattern=r"^\+\d{8,15}$")],
) -> dict[str, Any]:
    item = await _find(e164)
    first_charge = ledger.credits(number_setup_fee() + number_monthly_fee())
    return {
        **_offer(item),
        "first_charge": str(first_charge),
        "balance": str(await ledger.balance(session, user.account_id)),
        "kyc_required": await _verified_holder(session, user.account_id, None) is None,
    }


class Purchase(BaseModel):
    e164: Annotated[str, StringConstraints(pattern=r"^\+\d{8,15}$")]
    holder_id: uuid.UUID | None = None


@router.post("/numbers/purchase", status_code=status.HTTP_201_CREATED)
async def purchase(body: Purchase, user: OwnerUser, session: Session) -> dict[str, Any]:
    """Buy a number: the first month is taken from credits, then the carrier is asked; if the
    carrier refuses, the credits go back."""
    holder = await _verified_holder(session, user.account_id, body.holder_id)
    if holder is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "verify the number holder first (PAN, then Aadhaar through DigiLocker)",
        )
    held = await session.scalar(
        select(PhoneNumber.id).where(
            PhoneNumber.e164 == body.e164, PhoneNumber.status != NumberStatus.RELEASED
        )
    )
    if held is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "that number is already taken")
    store = _store()
    item = await _find(body.e164)
    reference = uuid.uuid4().hex
    charge = ledger.credits(number_setup_fee() + number_monthly_fee())
    await ledger.post(
        session, user.account_id, LedgerKind.NUMBER, -charge,
        ref_type="number_purchase", ref_id=reference, note=f"new number {item.e164}",
    )  # fmt: skip
    await session.commit()
    try:
        provider_ref = await store.buy_number(item.e164)
    except Exception:
        await ledger.post(
            session, user.account_id, LedgerKind.REFUND, charge,
            ref_type="number_purchase_refund", ref_id=reference, note=f"{item.e164} not bought",
        )  # fmt: skip
        await session.commit()
        raise
    number = PhoneNumber(
        account_id=user.account_id,
        provider=store.name,
        e164=item.e164,
        number_type=NumberType(item.number_type),
        channels=1,
        status=NumberStatus.ACTIVE,
        renews_on=next_month(today_ist(datetime.now(UTC))),
        provider_ref=provider_ref,
        holder_id=holder.id,
        monthly_fee=number_monthly_fee(),
    )
    session.add(number)
    await session.commit()
    return _number_out(number)


@router.delete("/numbers/{number_id}")
async def release(number_id: uuid.UUID, user: OwnerUser, session: Session) -> dict[str, str]:
    """Give a number back. Its employee is detached (and paused if it was live); the rent already
    paid is not refunded."""
    number = await attaching.load_number(session, user.account_id, number_id)
    if number.status is NumberStatus.RELEASED:
        raise HTTPException(status.HTTP_409_CONFLICT, "already released")
    await _store().release_number(number.e164)
    number.status = NumberStatus.RELEASED
    await attaching.detach_number(session, number.id)
    await session.commit()
    return {"status": NumberStatus.RELEASED.value}


class Channels(BaseModel):
    channels: Annotated[int, Field(ge=1, le=attaching.MAX_CHANNELS)]


@router.put("/numbers/{number_id}/channels")
async def set_channels(
    number_id: uuid.UUID, body: Channels, user: OwnerUser, session: Session
) -> dict[str, Any]:
    """How many calls the number can carry at once. Each extra channel is rented with the number
    from the next renewal."""
    number = await attaching.load_number(session, user.account_id, number_id)
    if number.status is NumberStatus.RELEASED:
        raise HTTPException(status.HTTP_409_CONFLICT, "a released number has no channels")
    number.channels = body.channels
    await session.commit()
    return _number_out(number)


# --- Which employee uses it --------------------------------------------------------------------


class Attach(BaseModel):
    number_id: uuid.UUID


@router.put("/employees/{employee_id}/number")
async def attach_number(
    employee_id: uuid.UUID, body: Attach, user: OwnerUser, session: Session
) -> dict[str, Any]:
    employee = await load(session, user, employee_id)
    number = await attaching.attach(session, employee, body.number_id)
    await session.commit()
    return _number_out(number, employee.id)


@router.delete("/employees/{employee_id}/number")
async def detach_number(
    employee_id: uuid.UUID, user: OwnerUser, session: Session
) -> dict[str, str]:
    employee = await load(session, user, employee_id)
    await attaching.detach(session, employee)
    await session.commit()
    return {"status": employee.status.value}


# --- KYC ---------------------------------------------------------------------------------------


def _holder_out(holder: KycHolder) -> dict[str, Any]:
    return {
        "id": holder.id,
        "name": holder.name,
        "pan_last4": holder.pan_last4,
        "status": holder.status,
    }


@router.get("/numbers/holders")
async def holders(user: CurrentUser, session: Session) -> list[dict[str, Any]]:
    rows = await session.scalars(
        select(KycHolder)
        .where(KycHolder.account_id == user.account_id)
        .order_by(KycHolder.created_at)
    )
    return [_holder_out(h) for h in rows]


class PanBody(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)]
    pan: Annotated[str, StringConstraints(pattern=PAN.pattern)]

    @field_validator("pan", mode="before")
    @classmethod
    def _upper(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


@router.post("/numbers/kyc/verify-pan", status_code=status.HTTP_201_CREATED)
async def verify_pan(body: PanBody, user: OwnerUser, session: Session) -> dict[str, Any]:
    """Step one. The PAN goes to the verifier; only its last four characters are kept."""
    result = await _kyc().verify_pan(body.pan, body.name)
    if not result.verified:
        raise HTTPException(422, "the PAN does not match that name")
    holder = KycHolder(
        account_id=user.account_id,
        name=result.name,
        pan_last4=body.pan[-4:],
        status=PAN_VERIFIED,
        provider_ref=result.holder_ref,
    )
    session.add(holder)
    await session.commit()
    return _holder_out(holder)


async def _holder(session: Session, account_id: uuid.UUID, holder_id: uuid.UUID) -> KycHolder:
    holder = await session.scalar(
        select(KycHolder).where(KycHolder.id == holder_id, KycHolder.account_id == account_id)
    )
    if holder is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "holder not found")
    return holder


class DigilockerStart(BaseModel):
    holder_id: uuid.UUID
    redirect_url: Annotated[str, StringConstraints(pattern=r"^https://", max_length=500)]


@router.post("/numbers/kyc/digilocker/initiate")
async def digilocker_initiate(
    body: DigilockerStart, user: OwnerUser, session: Session
) -> dict[str, str]:
    """Step two: where the holder gives Aadhaar consent."""
    holder = await _holder(session, user.account_id, body.holder_id)
    if holder.status != PAN_VERIFIED or not holder.provider_ref:
        raise HTTPException(status.HTTP_409_CONFLICT, "verify the PAN first")
    started = await _kyc().digilocker_start(holder.provider_ref, body.redirect_url)
    holder.digilocker_ref = started.ref
    await session.commit()
    return {"url": started.url}


class DigilockerCheck(BaseModel):
    holder_id: uuid.UUID


@router.post("/numbers/kyc/digilocker/verify")
async def digilocker_verify(
    body: DigilockerCheck, user: OwnerUser, session: Session
) -> dict[str, Any]:
    holder = await _holder(session, user.account_id, body.holder_id)
    if holder.status == VERIFIED:
        return _holder_out(holder)
    if holder.status != PAN_VERIFIED or not holder.provider_ref or not holder.digilocker_ref:
        raise HTTPException(status.HTTP_409_CONFLICT, "start the DigiLocker step first")
    if not await _kyc().digilocker_verified(holder.provider_ref, holder.digilocker_ref):
        raise HTTPException(status.HTTP_409_CONFLICT, "the holder has not finished DigiLocker yet")
    holder.status = VERIFIED
    await session.commit()
    return _holder_out(holder)
