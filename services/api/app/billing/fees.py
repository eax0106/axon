"""The fee for AI help (builder, chat sandbox, voice preview, analysis), taken from the wallet."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import ledger
from app.billing.config import ai_use_fee
from app.models import LedgerKind


async def charge_ai_use(
    session: AsyncSession,
    account_id: uuid.UUID,
    what: str,
    ref_id: str | None = None,
    *,
    allow_overdraw: bool = False,
) -> None:
    """Take one AI-use fee. Raises InsufficientCreditsError (served as 402) when the account is
    out of credits, unless the work is already done (`allow_overdraw`). Does not commit."""
    fee = ai_use_fee()
    if fee <= 0:
        return
    await ledger.post(
        session,
        account_id,
        LedgerKind.AI_USE,
        -fee,
        ref_type=f"ai:{what}",
        ref_id=ref_id or uuid.uuid4().hex,
        note=f"AI help: {what}",
        allow_overdraw=allow_overdraw,
    )


async def refund_ai_use(
    session: AsyncSession, account_id: uuid.UUID, what: str, ref_id: str
) -> None:
    """Give back a fee for AI help that failed before it delivered anything. Once per fee."""
    fee = ai_use_fee()
    if fee <= 0:
        return
    await ledger.post(
        session,
        account_id,
        LedgerKind.REFUND,
        fee,
        ref_type=f"ai_refund:{what}",
        ref_id=ref_id,
        note=f"AI help failed: {what}",
    )
