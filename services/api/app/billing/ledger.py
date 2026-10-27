"""The credit wallet: an append-only ledger and the balance it adds up to.

Every change goes through `post()`, which locks the account row, so the balance, each entry's
`balance_after` and the running sum stay equal however many workers post at once. A posting with
a reference (`ref_type`, `ref_id`) happens once: posting the same reference again returns the
first entry and changes nothing. That makes retried jobs, replayed webhooks and a browser racing
a webhook safe.
"""

import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.config import CREDIT_DECIMALS
from app.models import Account, LedgerKind, WalletEntry


class InsufficientCreditsError(Exception):
    def __init__(self, balance: Decimal, needed: Decimal) -> None:
        super().__init__(f"balance {balance} is below the {needed} needed")
        self.balance, self.needed = balance, needed


@dataclass(frozen=True)
class Posted:
    entry: WalletEntry
    created: bool  # False: this reference had already been posted


def credits(amount: Decimal | int | str) -> Decimal:
    """`amount` as credits: four decimals, half up."""
    return Decimal(amount).quantize(CREDIT_DECIMALS, rounding=ROUND_HALF_UP)


async def lock_account(session: AsyncSession, account_id: uuid.UUID) -> Account:
    account = await session.scalar(
        select(Account).where(Account.id == account_id).with_for_update()
    )
    if account is None:
        raise LookupError(f"no account {account_id}")
    return account


async def post(
    session: AsyncSession,
    account_id: uuid.UUID,
    kind: LedgerKind,
    amount: Decimal | int | str,
    *,
    ref_type: str | None = None,
    ref_id: str | None = None,
    note: str | None = None,
    allow_overdraw: bool = False,
) -> Posted:
    """Add `amount` (negative to spend) to the wallet. Does not commit.

    A spend that would take the balance below zero raises InsufficientCreditsError, unless
    `allow_overdraw`: that is for a charge for something already delivered (a call that has just
    ended), which must be recorded even if it leaves the account owing."""
    value = credits(amount)
    account = await lock_account(session, account_id)
    if ref_type is not None and ref_id is not None:
        existing = await session.scalar(
            select(WalletEntry).where(
                WalletEntry.account_id == account_id,
                WalletEntry.ref_type == ref_type,
                WalletEntry.ref_id == ref_id,
            )
        )
        if existing is not None:
            return Posted(existing, created=False)
    balance = account.credit_balance + value
    if value < 0 and balance < 0 and not allow_overdraw:
        raise InsufficientCreditsError(account.credit_balance, -value)
    entry = WalletEntry(
        account_id=account_id,
        kind=kind,
        amount=value,
        balance_after=balance,
        ref_type=ref_type,
        ref_id=ref_id,
        note=note,
    )
    account.credit_balance = balance
    session.add(entry)
    await session.flush()
    return Posted(entry, created=True)


async def balance(session: AsyncSession, account_id: uuid.UUID) -> Decimal:
    value = await session.scalar(select(Account.credit_balance).where(Account.id == account_id))
    return value if value is not None else Decimal(0)
