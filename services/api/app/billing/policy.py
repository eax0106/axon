"""Whether an account may start another call: it needs credits, and it must be under its hourly
spend cap. Checked by the dialer before every dial."""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, LedgerKind, WalletEntry


async def spent_last_hour(session: AsyncSession, account_id: uuid.UUID, now: datetime) -> Decimal:
    total = await session.scalar(
        select(func.coalesce(-func.sum(WalletEntry.amount), 0)).where(
            WalletEntry.account_id == account_id,
            WalletEntry.kind == LedgerKind.CALL,
            WalletEntry.created_at > now - timedelta(hours=1),
        )
    )
    return Decimal(total or 0)


async def blocked_reason(session: AsyncSession, account_id: uuid.UUID, now: datetime) -> str | None:
    """Why the account may not start a call right now, in plain words, or None."""
    account = await session.get(Account, account_id)
    assert account is not None  # FK guarantees it
    if account.credit_balance <= 0:
        return "no credits left: top up to keep calling"
    cap = account.spend_cap_per_hour
    if cap is not None and await spent_last_hour(session, account_id, now) >= cap:
        return f"the hourly spend cap of {cap:.2f} credits has been reached"
    return None
