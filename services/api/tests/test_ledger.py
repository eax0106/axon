"""The wallet ledger always adds up. A seeded random loop (stdlib `random`; the same seed replays
the same run) checks the invariants after every posting."""

import random
import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select

from app.billing import ledger
from app.models import Account, LedgerKind, WalletEntry

from .conftest import sql
from .helpers import run_db


def new_account(url: str, name: str = "A") -> uuid.UUID:
    return uuid.UUID(
        str(sql(url, "INSERT INTO accounts (name) VALUES (:n) RETURNING id", {"n": name}))
    )


async def check_invariants(session: Any, account_id: uuid.UUID) -> Decimal:
    """Balance = sum of the ledger, and every entry's balance_after is the running sum."""
    entries = list(
        await session.scalars(
            select(WalletEntry).where(WalletEntry.account_id == account_id).order_by(WalletEntry.id)
        )
    )
    running = Decimal(0)
    for entry in entries:
        running += entry.amount
        assert entry.balance_after == running, (entry.id, entry.balance_after, running)
    account = await session.get(Account, account_id)
    await session.refresh(account)
    assert account.credit_balance == running
    total = await session.scalar(
        select(func.coalesce(func.sum(WalletEntry.amount), 0)).where(
            WalletEntry.account_id == account_id
        )
    )
    assert Decimal(total) == running
    return running


def test_a_random_run_of_postings_always_balances(migrated_url: str) -> None:
    rng = random.Random(20261025)  # noqa: S311 - a replayable test seed, not security
    account = new_account(migrated_url)
    other = new_account(migrated_url, "B")

    async def work(factory: Any) -> None:
        used: list[str] = []
        refused = posted = repeats = 0
        for step in range(600):
            async with factory() as session:
                before = await ledger.balance(session, account)
                roll = rng.random()
                ref_type, ref_id = None, None
                if used and rng.random() < 0.15:  # repeat an earlier reference
                    ref_type, ref_id = "job", rng.choice(used)
                elif rng.random() < 0.7:
                    ref_type, ref_id = "job", f"r{step}"
                if roll < 0.35:
                    kind, amount = LedgerKind.TOPUP, Decimal(rng.randint(1, 50000)) / 100
                elif roll < 0.85:
                    kind, amount = LedgerKind.CALL, -Decimal(rng.randint(1, 3000000)) / 10000
                elif roll < 0.92:
                    kind, amount = LedgerKind.REFUND, Decimal(rng.randint(1, 1000)) / 100
                else:
                    kind, amount = LedgerKind.ADJUSTMENT, Decimal(rng.randint(-500, 500)) / 100
                try:
                    result = await ledger.post(
                        session, account, kind, amount, ref_type=ref_type, ref_id=ref_id
                    )
                except ledger.InsufficientCreditsError:
                    await session.rollback()
                    refused += 1
                    async with factory() as check:
                        assert (
                            await ledger.balance(check, account) == before
                        )  # a refusal changes nothing
                    continue
                if not result.created:
                    repeats += 1
                    assert ref_id is not None
                else:
                    posted += 1
                    if ref_id and ref_id not in used:
                        used.append(ref_id)
                await session.commit()
            if step % 25 == 0:
                async with factory() as session:
                    await check_invariants(session, account)
        async with factory() as session:
            final = await check_invariants(session, account)
            assert final >= 0  # no spend ever took it below zero (adjustments aside, see below)
            assert await ledger.balance(session, other) == 0  # the other account never moved
        assert posted > 100 and refused > 0 and repeats > 0  # the run exercised every path

    run_db(migrated_url, work)


def test_a_repeated_reference_posts_once_and_returns_the_first_entry(migrated_url: str) -> None:
    account = new_account(migrated_url)

    async def work(factory: Any) -> None:
        async with factory() as session:
            first = await ledger.post(
                session, account, LedgerKind.TOPUP, 100, ref_type="payment", ref_id="p1"
            )
            await session.commit()
        async with factory() as session:
            again = await ledger.post(
                session, account, LedgerKind.TOPUP, 999, ref_type="payment", ref_id="p1"
            )
            await session.commit()
            assert (
                not again.created and again.entry.id == first.entry.id and again.entry.amount == 100
            )
            assert await ledger.balance(session, account) == 100
        async with (
            factory() as session
        ):  # the same reference under another type or account is separate
            other_type = await ledger.post(
                session, account, LedgerKind.TOPUP, 5, ref_type="bonus", ref_id="p1"
            )
            assert other_type.created
            await session.commit()

    run_db(migrated_url, work)
    assert (
        sql(
            migrated_url, "SELECT count(*) FROM wallet_ledger WHERE account_id = :a", {"a": account}
        )
        == 2
    )


def test_the_database_refuses_a_duplicate_reference_even_if_the_code_were_bypassed(
    migrated_url: str,
) -> None:
    account = new_account(migrated_url)
    insert = (
        "INSERT INTO wallet_ledger (account_id, kind, amount, balance_after, ref_type, ref_id)"
        " VALUES (:a, 'topup', 1, 1, 'payment', 'p9')"
    )
    sql(migrated_url, insert, {"a": account})
    with pytest.raises(Exception, match="uq_wallet_ledger_ref"):
        sql(migrated_url, insert, {"a": account})
    plain = (
        "INSERT INTO wallet_ledger (account_id, kind, amount, balance_after)"
        " VALUES (:a, 'adjustment', 1, 2)"
    )
    sql(migrated_url, plain, {"a": account})
    sql(migrated_url, plain, {"a": account})  # entries without a reference may repeat


def test_amounts_are_exact_decimals_to_four_places(migrated_url: str) -> None:
    account = new_account(migrated_url)

    async def strict(factory: Any) -> None:
        async with factory() as session:
            await ledger.post(session, account, LedgerKind.TOPUP, "0.1")
            await ledger.post(session, account, LedgerKind.TOPUP, "0.2")
            assert await ledger.balance(session, account) == Decimal("0.3000")  # no float drift
            with pytest.raises(ledger.InsufficientCreditsError):
                await ledger.post(session, account, LedgerKind.CALL, "-0.30005")
            await session.rollback()

    run_db(migrated_url, strict)

    async def delivered(factory: Any) -> None:
        # A charge for something already delivered is recorded even if it leaves the account owing.
        async with factory() as session:
            await ledger.post(session, account, LedgerKind.TOPUP, "0.3")
            posted = await ledger.post(
                session, account, LedgerKind.CALL, "-0.30005", allow_overdraw=True
            )
            await session.commit()
            assert posted.entry.amount == Decimal("-0.3001")  # half up at four places
            assert posted.entry.balance_after == Decimal("-0.0001")

    run_db(migrated_url, delivered)


def test_unknown_accounts_are_an_error_not_a_silent_wallet(migrated_url: str) -> None:
    async def work(factory: Any) -> None:
        async with factory() as session:
            with pytest.raises(LookupError):
                await ledger.post(session, uuid.uuid4(), LedgerKind.TOPUP, 1)

    run_db(migrated_url, work)
