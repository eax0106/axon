"""What the channels of a number mean: calls it can carry at once, and what raising them costs.

A channel is one call in flight on the number. The dialer holds a call back while every channel is
busy, and raising the count is paid at once for the rest of the rental period, so that raising it
after a renewal and lowering it before the next one is not a way to use channels for free. Lowering
takes effect at once and is not refunded."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import ledger
from app.billing.config import extra_channel_monthly_fee
from app.models import Call, CallStatus, PhoneNumber

IN_FLIGHT = (CallStatus.RINGING, CallStatus.IN_PROGRESS)


async def busy(session: AsyncSession, number_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count()).where(Call.number_id == number_id, Call.status.in_(IN_FLIGHT))
        )
        or 0
    )


async def has_free_channel(session: AsyncSession, number: PhoneNumber) -> bool:
    """Is a channel free? The number's row is locked first, so two workers cannot both see the
    last free channel; the lock is held until the caller commits its claim."""
    await session.execute(
        select(PhoneNumber.id).where(PhoneNumber.id == number.id).with_for_update()
    )
    return await busy(session, number.id) < number.channels


def upgrade_fee(
    number: PhoneNumber, channels: int, today: date, period_start: date | None
) -> Decimal:
    """What going up to `channels` costs now: the monthly fee of each added channel for the days
    left until the next renewal. Nothing when the number has no renewal date (nothing is rented)."""
    added = channels - number.channels
    if added <= 0 or number.renews_on is None or period_start is None:
        return Decimal(0)
    period_days = (number.renews_on - period_start).days
    left = max(0, min(period_days, (number.renews_on - today).days))
    return ledger.credits(extra_channel_monthly_fee() * added * left / period_days)
