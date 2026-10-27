"""Per-account hourly limits for anything that costs us vendor money without charging the account.

The account row is locked while counting, so parallel requests cannot all slip under the limit.
Each use of AI help is also paid for in credits (app.billing.fees).
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.billing.fees import charge_ai_use, refund_ai_use
from app.db import Session
from app.models import Account, AuditEntry, User

AI_PER_HOUR = 60  # builder, chat sandbox, transcription and voice previews together
TEST_CALLS_PER_HOUR = 10  # phone and browser test calls together


async def take(session: AsyncSession, user: User, action: str, limit: int) -> None:
    """Record one use of `action` for the user's account, or answer 429 when the hour is full.
    Commits, which releases the account lock before the slow vendor call that follows."""
    await session.execute(select(Account.id).where(Account.id == user.account_id).with_for_update())
    since = datetime.now(UTC) - timedelta(hours=1)
    used = await session.scalar(
        select(func.count())
        .select_from(AuditEntry)
        .where(
            AuditEntry.account_id == user.account_id,
            AuditEntry.action == action,
            AuditEntry.created_at > since,
        )
    )
    if (used or 0) >= limit:
        await session.rollback()
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, f"limit of {limit} an hour for this account reached"
        )
    session.add(AuditEntry(account_id=user.account_id, actor_user_id=user.id, action=action))
    await session.commit()


async def ai_budget(user: CurrentUser, session: Session) -> AsyncIterator[None]:
    """Each use of AI help: within the account's hourly allowance, then paid for in credits. The
    fee goes back if the request then fails, so a vendor outage costs the customer nothing."""
    await take(session, user, "ai.request", AI_PER_HOUR)
    account_id, ref = user.account_id, uuid.uuid4().hex  # read now: a rollback expires `user`
    await charge_ai_use(session, account_id, "request", ref)
    await session.commit()
    try:
        yield
    except Exception:
        await session.rollback()
        await refund_ai_use(session, account_id, "request", ref)
        await session.commit()
        raise


async def ai_rate(user: CurrentUser, session: Session) -> None:
    """The hourly allowance without a fee, for work that is paid for elsewhere: a re-analysis (the
    analysis fee is taken once, when the analysis completes) and one chunk of a spoken brief (the
    brief pays when it goes to the builder, not for each chunk of audio)."""
    await take(session, user, "ai.request", AI_PER_HOUR)


AiBudget = Depends(ai_budget)
AiRate = Depends(ai_rate)
