"""Admin console: the voice library, the vendors (live health, rates, costs, balances) and the
carrier (capacity, and purchases waiting for a person to settle them).

The vendors' own probe (keys set, adapter answering) is `/admin/providers` in `app.main`; the
live score here is what calls and dials have just seen (`app.providers.health`)."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from app.admin.accounts import Staff, audit
from app.auth import require_admin
from app.billing import ledger
from app.db import Session
from app.models import (
    Employee,
    LedgerKind,
    Notification,
    NumberStatus,
    PhoneNumber,
    ProviderBalance,
    ProviderRate,
    Voice,
    WalletEntry,
)
from app.numbers.renewals import next_month, today_ist
from app.providers import costs, failover, health
from app.providers.registry import TIER_TTS, VENDOR_KEYS
from app.settings import max_concurrent_calls
from app.voices import VoiceOut, voice_out

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
Language = Literal["te", "hi", "en"]
COST_DAYS_MAX = 366


# --- the voice library -------------------------------------------------------------------------


class VoiceIn(BaseModel):
    """A voice from a vendor's catalogue. Its tier (and so its price) follows from the vendor."""

    provider: str = Field(max_length=50)
    provider_voice_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=100)
    native_language: Language
    accent: str | None = Field(default=None, max_length=50)
    tone_tags: list[str] = Field(default_factory=list, max_length=10)
    language_scores: dict[Language, float] = Field(min_length=1)


def _fill(voice: Voice, body: VoiceIn) -> None:
    tier = failover.TTS_TIER.get(body.provider)
    if tier is None:
        known = ", ".join(TIER_TTS.values())
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"provider must be {known}")
    if any(not 0 <= score <= 1 for score in body.language_scores.values()):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "scores are 0 to 1")
    voice.provider, voice.provider_voice_id, voice.tier = (
        body.provider,
        body.provider_voice_id,
        tier,
    )
    voice.public_name, voice.native_language = body.name, body.native_language
    voice.accent, voice.tone_tags = body.accent, [t[:50] for t in body.tone_tags]
    voice.language_scores = {str(k): v for k, v in body.language_scores.items()}


async def _save(session: Session, voice: Voice) -> VoiceOut:
    try:
        await session.commit()
    except IntegrityError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "that voice is already in the library"
        ) from exc
    return voice_out(voice)


async def _voice(session: Session, voice_id: uuid.UUID) -> Voice:
    voice = await session.get(Voice, voice_id)
    if voice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "voice not found")
    return voice


@router.post("/voices", status_code=status.HTTP_201_CREATED)
async def create_voice(body: VoiceIn, staff: Staff, session: Session) -> VoiceOut:
    voice = Voice()
    _fill(voice, body)
    session.add(voice)
    audit(session, staff, None, "voice_created", voice=body.provider_voice_id)
    return await _save(session, voice)


@router.put("/voices/{voice_id}")
async def update_voice(
    voice_id: uuid.UUID, body: VoiceIn, staff: Staff, session: Session
) -> VoiceOut:
    voice = await _voice(session, voice_id)
    _fill(voice, body)
    audit(session, staff, None, "voice_updated", voice=str(voice_id))
    return await _save(session, voice)


@router.delete("/voices/{voice_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_voice(voice_id: uuid.UUID, staff: Staff, session: Session) -> None:
    """Only a voice no employee uses can go: removing one would change how those employees sound."""
    voice = await _voice(session, voice_id)
    users = await session.scalar(select(func.count()).where(Employee.voice_id == voice_id))
    if users:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{users} employee(s) use this voice")
    await session.delete(voice)
    audit(session, staff, None, "voice_deleted", voice=str(voice_id))
    await session.commit()


# --- the vendors -------------------------------------------------------------------------------


@router.get("/provider-health")
async def provider_health(session: Session) -> dict[str, Any]:
    """Each vendor's outcomes over the last minutes, and whether calls avoid it right now."""
    scores = await health.scores(session, datetime.now(UTC))
    rows = []
    for kind, vendors in VENDOR_KEYS.items():
        for vendor in vendors:
            score = scores.get((str(kind), vendor), health.Score(str(kind), vendor, 0, 0))
            rows.append(
                {
                    "kind": str(kind),
                    "vendor": vendor,
                    "ok": score.ok,
                    "failed": score.failed,
                    "success_rate": score.success_rate,
                    "healthy": score.healthy,
                }
            )
    return {"window_minutes": int(health.WINDOW.total_seconds() // 60), "providers": rows}


class RateIn(BaseModel):
    kind: str = Field(max_length=20)
    vendor: str = Field(max_length=50)
    unit: str = Field(max_length=30)
    inr_per_unit: Decimal = Field(ge=0, max_digits=16, decimal_places=8)


@router.get("/provider-rates")
async def list_rates(session: Session) -> list[RateIn]:
    rows = await session.scalars(
        select(ProviderRate).order_by(ProviderRate.kind, ProviderRate.vendor, ProviderRate.unit)
    )
    return [
        RateIn(kind=r.kind, vendor=r.vendor, unit=r.unit, inr_per_unit=r.inr_per_unit) for r in rows
    ]


@router.put("/provider-rates")
async def set_rate(body: RateIn, staff: Staff, session: Session) -> RateIn:
    """Enter what one unit of a vendor's usage costs, from its price list (replaces the old)."""
    known = {(str(k), v) for k, vendors in VENDOR_KEYS.items() for v in vendors}
    if (body.kind, body.vendor) not in known:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown vendor")
    await session.execute(
        insert(ProviderRate)
        .values(**body.model_dump())
        .on_conflict_do_update(
            index_elements=["kind", "vendor", "unit"], set_={"inr_per_unit": body.inr_per_unit}
        )
    )
    audit(session, staff, None, "provider_rate_set", **body.model_dump(mode="json"))
    await session.commit()
    return body


@router.get("/provider-costs")
async def provider_costs(
    session: Session, days: Annotated[int, Query(ge=1, le=COST_DAYS_MAX)] = 30
) -> dict[str, Any]:
    """Usage and cost per vendor over the last `days`. Cost is empty where no rate is entered."""
    until = datetime.now(UTC)
    rows = await costs.usage(session, until - timedelta(days=days), until)
    return {
        "days": days,
        "total_inr": costs.total(rows),
        "unpriced": sorted({f"{r.kind}/{r.vendor}/{r.unit}" for r in rows if r.rate is None}),
        "items": [
            {
                "kind": r.kind,
                "vendor": r.vendor,
                "unit": r.unit,
                "usage": r.amount,
                "inr_per_unit": r.rate,
                "cost_inr": r.cost,
            }
            for r in rows
        ],
    }


class BalanceIn(BaseModel):
    balance_inr: Decimal = Field(max_digits=14, decimal_places=2)
    alert_below_inr: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)


async def balances(session: Session, now: datetime) -> list[dict[str, Any]]:
    """Each vendor's balance as staff last read it, less what was used since (at known rates)."""
    out = []
    for row in await session.scalars(select(ProviderBalance).order_by(ProviderBalance.vendor)):
        spent = costs.total(await costs.usage(session, row.recorded_at, now, vendor=row.vendor))
        left = row.balance_inr - spent
        out.append(
            {
                "vendor": row.vendor,
                "recorded_inr": row.balance_inr,
                "recorded_at": row.recorded_at,
                "spent_since_inr": spent,
                "estimated_inr": left,
                "alert_below_inr": row.alert_below_inr,
                "low": row.alert_below_inr is not None and left < row.alert_below_inr,
            }
        )
    return out


@router.get("/provider-balances")
async def list_balances(session: Session) -> list[dict[str, Any]]:
    return await balances(session, datetime.now(UTC))


@router.put("/provider-balances/{vendor}")
async def set_balance(
    vendor: str, body: BalanceIn, staff: Staff, session: Session
) -> dict[str, Any]:
    """Record the balance just read off the vendor's dashboard; spend is counted from now."""
    if not any(vendor in vendors for vendors in VENDOR_KEYS.values()):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown vendor")
    values = {**body.model_dump(), "recorded_at": datetime.now(UTC)}
    await session.execute(
        insert(ProviderBalance)
        .values(vendor=vendor, **values)
        .on_conflict_do_update(index_elements=["vendor"], set_=values)
    )
    audit(
        session, staff, None, "provider_balance_set", vendor=vendor, **body.model_dump(mode="json")
    )
    await session.commit()
    return next(b for b in await balances(session, datetime.now(UTC)) if b["vendor"] == vendor)


# --- the carrier -------------------------------------------------------------------------------


@router.get("/capacity")
async def capacity(session: Session) -> dict[str, Any]:
    """How many calls the platform carries at once, how many are up, and the numbers' lines."""
    held = (PhoneNumber.status == NumberStatus.ACTIVE) | (PhoneNumber.status == NumberStatus.GRACE)
    lines = await session.execute(
        select(func.count(), func.coalesce(func.sum(PhoneNumber.channels), 0)).where(held)
    )
    numbers, channels = lines.one()
    reconcile = await session.scalars(
        select(PhoneNumber)
        .where(PhoneNumber.status == NumberStatus.RECONCILE)
        .order_by(PhoneNumber.created_at)
    )
    return {
        "max_concurrent_calls": max_concurrent_calls(),
        "calls_in_flight": await failover.in_flight(session),
        "numbers": numbers,
        "channels": int(channels),
        "reconcile": [
            {
                "id": n.id,
                "account_id": n.account_id,
                "e164": n.e164,
                "provider": n.provider,
                "created_at": n.created_at,
            }
            for n in reconcile
        ],
    }


class Settle(BaseModel):
    outcome: Literal["kept", "refunded"]
    provider_ref: str | None = Field(default=None, max_length=100)  # the carrier's id, if kept
    note: str = Field(min_length=3, max_length=300)


@router.post("/numbers/{number_id}/settle")
async def settle_purchase(
    number_id: uuid.UUID, body: Settle, staff: Staff, session: Session
) -> dict[str, Any]:
    """A number bought while the carrier's answer was lost. After checking with the carrier: it
    was sold (`kept`: the number goes live, the charge stands) or not (`refunded`: the charge
    goes back). Once only."""
    number = await session.get(PhoneNumber, number_id, with_for_update=True)
    if number is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "number not found")
    if number.status is not NumberStatus.RECONCILE:
        raise HTTPException(status.HTTP_409_CONFLICT, "this purchase is already settled")
    if body.outcome == "kept":
        number.status, number.provider_ref = NumberStatus.ACTIVE, body.provider_ref
        number.renews_on = next_month(today_ist(datetime.now(UTC)))
        title, text = f"Your number {number.e164} is ready", "The carrier confirmed the purchase."
    else:
        charge = await session.scalar(
            select(WalletEntry).where(
                WalletEntry.account_id == number.account_id,
                WalletEntry.ref_type == "number_purchase",
                WalletEntry.ref_id == number.id.hex,
            )
        )
        number.status = NumberStatus.RELEASED
        if charge is not None:
            await ledger.post(
                session, number.account_id, LedgerKind.REFUND, -charge.amount,
                ref_type="number_purchase_refund", ref_id=number.id.hex,
                note=f"{number.e164} not bought",
            )  # fmt: skip
        title = f"Your number {number.e164} could not be bought"
        text = "The carrier did not sell it. The credits are back in your wallet."
    session.add(
        Notification(account_id=number.account_id, kind="number_purchase", title=title, body=text)
    )
    audit(
        session,
        staff,
        number.account_id,
        "number_settled",
        number=str(number.id),
        outcome=body.outcome,
        note=body.note,
    )
    await session.commit()
    return {"id": number.id, "status": number.status.value}
