"""Low-balance warnings: an entry in the notification bell when the balance drops under the
threshold, and an email at most once a day."""

import logging
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.config import low_balance_threshold
from app.models import Account, Notification, User
from app.providers.base import EmailProvider, ProviderKind, ProviderNotConfiguredError
from app.providers.registry import require

log = logging.getLogger("axon.billing")
EMAIL_EVERY = timedelta(days=1)


async def after_spend(
    session: AsyncSession, account_id: uuid.UUID, balance: Decimal, spent: Decimal, now: datetime
) -> bool:
    """Call after a charge, inside the same transaction. Notes the account when this charge took
    it from above the threshold to under it. Returns True when an email should be sent (once the
    transaction has committed: see `send_low_balance_email`)."""
    threshold = low_balance_threshold()
    if not (balance < threshold <= balance + spent):
        return False
    account = await session.get(Account, account_id)
    assert account is not None  # FK guarantees it
    session.add(
        Notification(
            account_id=account_id,
            kind="low_balance",
            title="Low credit balance",
            body=f"You have {balance:.2f} credits left. Top up so your employees can keep calling.",
        )
    )
    due = (
        account.low_balance_emailed_at is None or account.low_balance_emailed_at < now - EMAIL_EVERY
    )
    if due:
        account.low_balance_emailed_at = now
    return due


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


async def send_low_balance_email(
    session: AsyncSession, account_id: uuid.UUID, balance: Decimal
) -> bool:
    return await email_owner(
        session,
        account_id,
        "Your credit balance is low",
        f"You have {balance:.2f} credits left. Top up so your employees can keep calling.",
    )
