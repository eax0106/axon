"""Number rental: paid monthly from credits, with a grace period, then released.

  active --due, enough credits--> active (renews_on moves a month on, one charge for the month)
  active --due, not enough-----> grace   (works as before; the owner is told; grace_until set)
  grace  --credits arrive------> active  (the top-up retries it at once; so does each tick)
  grace  --grace_until passed--> released (given back to the carrier, detached from its employee,
                                            which is paused; nothing else is deleted)

A period is charged under the reference `<number id>:<renews_on>`, so a retried tick, a top-up
racing the worker, or a crash after the charge can never bill the same month twice. All dates are
Indian dates (DECISIONS: fixed IST).
"""

import calendar
import logging
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.billing import alerts, ledger
from app.billing.config import extra_channel_monthly_fee, grace_days
from app.models import LedgerKind, Notification, NumberStatus, PhoneNumber
from app.numbers.attach import detach_number
from app.providers.base import NumberStore, ProviderKind, ProviderNotConfiguredError
from app.providers.registry import require

log = logging.getLogger("axon.numbers")
IST = timedelta(hours=5, minutes=30)
REF = "number_renewal"


def today_ist(now: datetime) -> date:
    return (now + IST).date()


def next_month(day: date) -> date:
    """The same day next month, or the month's last day when it has none (31 January -> 28
    February)."""
    year, month = (day.year + (day.month == 12), day.month % 12 + 1)
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def prev_month(day: date) -> date:
    """The same day last month, or that month's last day when it has none."""
    year, month = (day.year - (day.month == 1), (day.month - 2) % 12 + 1)
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def fee(number: PhoneNumber) -> Decimal:
    """What one month costs: the number's own fee plus each extra channel."""
    return ledger.credits(number.monthly_fee + (number.channels - 1) * extra_channel_monthly_fee())


async def _pay(session: AsyncSession, number: PhoneNumber) -> bool:
    """Charge the period that is due. False when the account cannot afford it."""
    assert number.renews_on is not None
    try:
        await ledger.post(
            session,
            number.account_id,
            LedgerKind.NUMBER,
            -fee(number),
            ref_type=REF,
            ref_id=f"{number.id}:{number.renews_on}",
            note=f"rent for {number.e164}",
        )
    except ledger.InsufficientCreditsError:
        return False
    number.renews_on = next_month(number.renews_on)
    number.status, number.grace_until = NumberStatus.ACTIVE, None
    return True


def _note(session: AsyncSession, number: PhoneNumber, kind: str, title: str, body: str) -> None:
    session.add(Notification(account_id=number.account_id, kind=kind, title=title, body=body))


async def renew_one(session: AsyncSession, number_id: uuid.UUID, today: date) -> str | None:
    """Move one number through the state machine as of `today`. Returns what happened
    (renewed, grace, released, waiting) or None when nothing was due. Does not commit.

    The account is locked before the number everywhere, so a top-up (which holds the account)
    and the worker cannot deadlock."""
    peek = await session.get(PhoneNumber, number_id)
    if peek is None:
        return None
    await ledger.lock_account(session, peek.account_id)
    number = await session.get(PhoneNumber, number_id, with_for_update=True, populate_existing=True)
    if (
        number is None
        or number.status is NumberStatus.RELEASED
        or number.renews_on is None
        or number.renews_on > today
    ):
        return None
    if await _pay(session, number):
        return "renewed"
    if number.status is NumberStatus.ACTIVE:
        number.status = NumberStatus.GRACE
        number.grace_until = number.renews_on + timedelta(days=grace_days())
        _note(
            session,
            number,
            "number_grace",
            f"Top up to keep {number.e164}",
            f"Rent of {fee(number):.2f} credits could not be taken. {number.e164} keeps working "
            f"until {number.grace_until}; after that it is released.",
        )
        return "grace"
    assert number.grace_until is not None
    if today <= number.grace_until:
        return "waiting"
    return "released" if await _release(session, number) else "waiting"


async def _release(session: AsyncSession, number: PhoneNumber) -> bool:
    """Give the number back to the carrier. If the carrier cannot be reached it stays in grace
    and is tried again on the next tick."""
    try:
        store = require(ProviderKind.TELEPHONY)
        assert isinstance(store, NumberStore)
        await store.release_number(number.e164)
    except ProviderNotConfiguredError:
        return False
    except Exception as exc:
        log.warning("release of %s failed: %s", number.e164, type(exc).__name__)
        return False
    number.status = NumberStatus.RELEASED
    await detach_number(session, number.id)
    _note(
        session,
        number,
        "number_released",
        f"{number.e164} was released",
        "The rent was not paid within the grace period. Its employee is paused; buy a number "
        "and attach it to bring the employee back.",
    )
    return True


async def renew_due(factory: async_sessionmaker[AsyncSession], now: datetime) -> dict[str, int]:
    """One tick: every number that is due or in grace. Counts of what happened."""
    counts = {"renewed": 0, "grace": 0, "released": 0, "waiting": 0}
    today = today_ist(now)
    async with factory() as session:
        ids = list(
            await session.scalars(
                select(PhoneNumber.id)
                .where(
                    PhoneNumber.status.in_((NumberStatus.ACTIVE, NumberStatus.GRACE)),
                    PhoneNumber.renews_on <= today,
                )
                .order_by(PhoneNumber.renews_on)
            )
        )
    for number_id in ids:
        async with factory() as session:
            outcome = await renew_one(session, number_id, today)
            number = await session.get(PhoneNumber, number_id)
            assert number is not None
            account_id = number.account_id
            e164 = number.e164
            await session.commit()
        if outcome in counts:
            counts[outcome] += 1
        if outcome in ("grace", "released"):
            async with factory() as session:
                title = "Top up to keep your number" if outcome == "grace" else "Number released"
                await alerts.email_owner(
                    session, account_id, f"{title}: {e164}", _email(outcome, e164)
                )
    return counts


def _email(outcome: str, e164: str) -> str:
    if outcome == "grace":
        return (
            f"The monthly rent for {e164} could not be taken because your credits ran out. "
            "It keeps working for a few more days. Top up your credits and it renews by itself."
        )
    return (
        f"The rent for {e164} was not paid in time, so the number was released and its "
        "employee paused. Buy a number and attach it to bring the employee back."
    )


async def recover(session: AsyncSession, account_id: uuid.UUID, today: date) -> int:
    """After a top-up: renew the account's numbers that are waiting on credits. Does not
    commit; the account is already locked by the caller's ledger posting."""
    ids = list(
        await session.scalars(
            select(PhoneNumber.id).where(
                PhoneNumber.account_id == account_id,
                PhoneNumber.status == NumberStatus.GRACE,
                PhoneNumber.renews_on <= today,
            )
        )
    )
    renewed = 0
    for number_id in ids:
        number = await session.get(PhoneNumber, number_id, with_for_update=True)
        assert number is not None
        renewed += await _pay(session, number)
    return renewed
