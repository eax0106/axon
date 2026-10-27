"""Many workers at once: exactly-once for a reference, exact totals, no overdraw."""

import asyncio
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.billing import ledger
from app.models import LedgerKind, WalletEntry

from .conftest import sql
from .helpers import run_db
from .test_ledger import check_invariants, new_account


async def post_in_own_session(
    factory: Any, account: uuid.UUID, kind: LedgerKind, amount: Any, ref: str | None, **kw: Any
) -> str:
    """One worker: its own session and transaction. Returns what happened."""
    async with factory() as session:
        try:
            posted = await ledger.post(
                session, account, kind, amount, ref_type="job" if ref else None, ref_id=ref, **kw
            )
        except ledger.InsufficientCreditsError:
            await session.rollback()
            return "refused"
        await session.commit()
        return "posted" if posted.created else "repeat"


def test_the_same_reference_from_many_workers_lands_exactly_once(migrated_url: str) -> None:
    account = new_account(migrated_url)

    async def work(factory: Any) -> list[str]:
        return list(
            await asyncio.gather(
                *(
                    post_in_own_session(factory, account, LedgerKind.TOPUP, 100, "payment-1")
                    for _ in range(25)
                )
            )
        )

    outcomes = run_db(migrated_url, work)
    assert outcomes.count("posted") == 1 and outcomes.count("repeat") == 24
    assert (
        sql(
            migrated_url, "SELECT count(*) FROM wallet_ledger WHERE account_id = :a", {"a": account}
        )
        == 1
    )
    assert sql(
        migrated_url, "SELECT credit_balance FROM accounts WHERE id = :a", {"a": account}
    ) == Decimal("100")


def test_distinct_postings_all_land_and_the_totals_are_exact(migrated_url: str) -> None:
    account = new_account(migrated_url)

    async def work(factory: Any) -> None:
        await asyncio.gather(
            *(
                post_in_own_session(factory, account, LedgerKind.TOPUP, Decimal(i) / 100, f"t{i}")
                for i in range(1, 41)
            )
        )
        async with factory() as session:
            final = await check_invariants(session, account)
        assert final == Decimal(sum(range(1, 41))) / 100

    run_db(migrated_url, work)
    ids = sql(
        migrated_url,
        "SELECT count(DISTINCT balance_after) FROM wallet_ledger WHERE account_id = :a",
        {"a": account},
    )
    assert ids == 40  # every posting saw the previous balance: no two share a running total


def test_spends_racing_for_the_last_credits_never_overdraw(migrated_url: str) -> None:
    account = new_account(migrated_url)

    async def work(factory: Any) -> list[str]:
        await post_in_own_session(factory, account, LedgerKind.TOPUP, 10, "seed")
        outcomes = list(
            await asyncio.gather(
                *(
                    post_in_own_session(factory, account, LedgerKind.CALL, -1, f"call-{i}")
                    for i in range(18)
                )
            )
        )
        async with factory() as session:
            await check_invariants(session, account)
        return outcomes

    outcomes = run_db(migrated_url, work)
    assert outcomes.count("posted") == 10 and outcomes.count("refused") == 8
    assert sql(
        migrated_url, "SELECT credit_balance FROM accounts WHERE id = :a", {"a": account}
    ) == Decimal("0")
    assert sql(
        migrated_url,
        "SELECT min(balance_after) FROM wallet_ledger WHERE account_id = :a",
        {"a": account},
    ) == Decimal("0")


def test_a_charge_for_a_delivered_call_is_recorded_once_even_when_it_overdraws(
    migrated_url: str,
) -> None:
    account = new_account(migrated_url)

    async def work(factory: Any) -> list[str]:
        return list(
            await asyncio.gather(
                *(
                    post_in_own_session(
                        factory, account, LedgerKind.CALL, "-2.5", "call-9", allow_overdraw=True
                    )
                    for _ in range(10)
                )
            )
        )

    outcomes = run_db(migrated_url, work)
    assert outcomes.count("posted") == 1
    assert sql(
        migrated_url, "SELECT credit_balance FROM accounts WHERE id = :a", {"a": account}
    ) == Decimal("-2.5")


def test_accounts_do_not_block_each_other(migrated_url: str) -> None:
    one, two = new_account(migrated_url, "one"), new_account(migrated_url, "two")

    async def work(factory: Any) -> None:
        jobs = [
            post_in_own_session(factory, a, LedgerKind.TOPUP, 1, f"{a}-{i}")
            for a in (one, two)
            for i in range(15)
        ]
        assert set(await asyncio.gather(*jobs)) == {"posted"}
        async with factory() as session:
            for a in (one, two):
                assert await check_invariants(session, a) == 15
            assert not list(
                await session.scalars(
                    select(WalletEntry).where(
                        WalletEntry.account_id == one, WalletEntry.balance_after > 15
                    )
                )
            )

    run_db(migrated_url, work)
