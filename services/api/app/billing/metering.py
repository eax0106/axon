"""Bill calls from the carrier's own record.

A call is charged for the seconds of talk time (`billsec`) in the authenticated call detail record
that Vobiz keeps, at the per-minute rate of the voice tier it ran on. Ringing, busy and no-answer
are free. The unsigned end-of-call callback never decides a charge, and a call with no carrier
record is never charged: after a day it is flagged `reconcile` for a person to look at.
"""

import logging
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.billing import alerts, ledger
from app.billing.config import rate_per_minute
from app.instant.dialer import _detail
from app.models import Call, CallEvent, CallStatus, Employee, LedgerKind, Voice, VoiceTier
from app.providers.base import TelephonyProvider

log = logging.getLogger("axon.billing")
FINAL = (CallStatus.COMPLETED, CallStatus.NO_ANSWER, CallStatus.BUSY, CallStatus.FAILED)
WAIT_FOR_RECORD = timedelta(seconds=30)  # the carrier writes its record just after the call ends
GIVE_UP_AFTER = timedelta(hours=24)
BATCH = 20


def call_charge(tier: str | VoiceTier, talk_seconds: int) -> Decimal:
    """Credits for `talk_seconds` of talk time on `tier`: the per-minute rate, per second."""
    return ledger.credits(rate_per_minute(tier) * Decimal(talk_seconds) / Decimal(60))


async def _tier(session: AsyncSession, call: Call) -> str:
    """The tier the call ran on; for a call recorded without one, its employee's voice today."""
    if call.voice_tier:
        return call.voice_tier
    employee = await session.get(Employee, call.employee_id) if call.employee_id else None
    voice = await session.get(Voice, employee.voice_id) if employee and employee.voice_id else None
    return voice.tier.value if voice else VoiceTier.VALUE.value


async def bill_pending(
    factory: async_sessionmaker[AsyncSession],
    telephony: TelephonyProvider,
    now: datetime,
    *,
    limit: int = BATCH,
) -> dict[str, int]:
    """Look at finished calls not yet billed; counts of billed, free, flagged and still waiting."""
    counts = {"billed": 0, "free": 0, "reconcile": 0, "waiting": 0}
    async with factory() as session:
        ids = list(
            await session.scalars(
                select(Call.id)
                .where(
                    Call.billing_status.is_(None),
                    Call.is_test.is_(False),
                    Call.status.in_(FINAL),
                    Call.ended_at < now - WAIT_FOR_RECORD,
                    Call.carrier_call_id.is_not(None),
                )
                .order_by(Call.ended_at)
                .limit(limit)
            )
        )
    for call_id in ids:
        counts[await _bill_one(factory, telephony, call_id, now)] += 1
    return counts


async def _bill_one(
    factory: async_sessionmaker[AsyncSession],
    telephony: TelephonyProvider,
    call_id: object,
    now: datetime,
) -> str:
    async with factory() as session:
        call = await session.get(Call, call_id, with_for_update=True)
        if call is None or call.billing_status is not None:
            return "waiting"
        try:
            detail = await _detail(telephony, call)
        except Exception as exc:  # an outage at the carrier: try again next tick
            log.warning("carrier record for call %s unavailable: %s", call.id, type(exc).__name__)
            return "waiting"
        if detail is None:
            if call.ended_at is not None and call.ended_at < now - GIVE_UP_AFTER:
                call.billing_status = "reconcile"
                session.add(CallEvent(call_id=call.id, type="billing_reconcile", data={}))
                await session.commit()
                return "reconcile"
            return "waiting"
        if not detail.answered or detail.talk_s <= 0:
            call.billing_status = "free"
            await session.commit()
            return "free"
        charge = call_charge(await _tier(session, call), detail.talk_s)
        posted = await ledger.post(
            session,
            call.account_id,
            LedgerKind.CALL,
            -charge,
            ref_type="call",
            ref_id=str(call.id),
            note=f"{detail.talk_s} s talk time",
            allow_overdraw=True,  # the call already happened
        )
        call.credits_charged = -posted.entry.amount
        call.billed_seconds = detail.talk_s
        call.billing_status = "billed"
        email_due = await alerts.after_spend(
            session, call.account_id, posted.entry.balance_after, charge, now
        )
        await session.commit()
        balance_now = posted.entry.balance_after
        account_id = call.account_id
    if email_due:
        async with factory() as session:
            await alerts.send_low_balance_email(session, account_id, balance_now)
    return "billed"
