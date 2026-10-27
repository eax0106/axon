"""Low-balance warnings: an entry in the notification bell when the balance drops under the
threshold, and an email at most once a day."""

import logging
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.billing.config import low_balance_threshold
from app.models import Account, Notification, User
from app.providers.base import EmailProvider, ProviderKind, ProviderNotConfiguredError
from app.providers.registry import require

log = logging.getLogger("axon.billing")
EMAIL_EVERY = timedelta(days=1)


def note_crossing(
    session: AsyncSession, account: Account, before: Decimal, after: Decimal, now: datetime
) -> None:
    """Called by the ledger for every spend, inside the same transaction. When this spend took the
    balance from the threshold or above to under it, the bell gets an entry, and the account is
    marked for an email if none went out in the last day (the worker sends it: see `send_pending`).
    """
    threshold = low_balance_threshold()
    if not (after < threshold <= before):
        return
    session.add(
        Notification(
            account_id=account.id,
            kind="low_balance",
            title="Low credit balance",
            body=f"You have {after:.2f} credits left. Top up so your employees can keep calling.",
        )
    )
    if account.low_balance_emailed_at is None or account.low_balance_emailed_at < now - EMAIL_EVERY:
        account.low_balance_emailed_at = now
        account.low_balance_email_pending = True


async def send_pending(factory: async_sessionmaker[AsyncSession]) -> int:
    """Email every account marked by `note_crossing`. The mark is cleared before sending, so a
    crash loses one email rather than sending it twice. Returns how many were attempted."""
    async with factory() as session:
        ids = list(
            await session.scalars(select(Account.id).where(Account.low_balance_email_pending))
        )
    sent = 0
    for account_id in ids:
        async with factory() as session:
            account = await session.get(Account, account_id, with_for_update=True)
            if account is None or not account.low_balance_email_pending:
                continue
            account.low_balance_email_pending = False
            balance = account.credit_balance
            await session.commit()
            await email_owner(
                session,
                account_id,
                "Your credit balance is low",
                f"You have {balance:.2f} credits left. Top up so your employees can keep calling.",
            )
            sent += 1
    return sent


async def email_owner(
    session: AsyncSession, account_id: uuid.UUID, subject: str, text: str
) -> bool:
    """Email the account owner. Best effort: no email provider or a failed send is logged, never
    raised, because the event it reports has already happened."""
    owner = await session.scalar(
        select(User).where(User.account_id == account_id).order_by(User.created_at).limit(1)
    )
    if owner is None:
        return False
    try:
        provider = require(ProviderKind.EMAIL)
        assert isinstance(provider, EmailProvider)
        await provider.send(owner.email, subject, text)
    except ProviderNotConfiguredError:
        return False
    except Exception as exc:
        log.warning("email %r failed: %s", subject, type(exc).__name__)
        return False
    return True
