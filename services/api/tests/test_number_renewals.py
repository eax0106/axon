"""Number rent under simulated time: renew, grace, recover, release; never a period twice."""

import json
import random
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.billing import alerts, ledger, payments
from app.models import LedgerKind, WalletEntry
from app.numbers import renewals
from app.providers.email.resend import ResendEmail

from .conftest import sql
from .helpers import account_id, give_credits, live_employee, run_db, seed, signup
from .vobiz_fake import VobizAccount

DUE = date(2026, 11, 15)
E164 = "+911400000001"


def at(day: date, hour: int = 6) -> datetime:
    """06:00 Indian time on `day`, as the worker's clock would read."""
    return datetime(day.year, day.month, day.day, hour, 0, tzinfo=UTC) - timedelta(
        hours=5, minutes=30
    )


@pytest.fixture
def api(db_client: TestClient, migrated_url: str) -> TestClient:
    seed(migrated_url)
    return db_client


class Mailbox:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "e"})


@pytest.fixture
def mailbox(monkeypatch: pytest.MonkeyPatch) -> Mailbox:
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("EMAIL_FROM", "billing@example.in")
    box = Mailbox()
    monkeypatch.setattr(
        alerts, "require", lambda _kind: ResendEmail(transport=httpx.MockTransport(box.handler))
    )
    return box


def rented(
    api: TestClient, url: str, credits: str, due: date = DUE
) -> tuple[str, str, str, dict[str, str]]:
    """(account, number id, employee, owner headers): a live employee on a rented number."""
    owner = signup(api)
    mine = account_id(api, owner)
    employee = live_employee(api, url, owner, number=E164)
    number = sql(
        url,
        "UPDATE numbers SET monthly_fee = 649, renews_on = :d, provider = 'vobiz' RETURNING id",
        {"d": due},
    )
    sql(url, "UPDATE accounts SET credit_balance = 0")
    sql(url, "DELETE FROM wallet_ledger")
    if Decimal(credits):
        give_credits(url, mine, credits)
    return mine, str(number), employee, owner


def tick(url: str, now: datetime) -> dict[str, int]:
    counts: dict[str, int] = run_db(url, lambda f: renewals.renew_due(f, now))
    return counts


def number(url: str, column: str) -> Any:
    return sql(url, f"SELECT {column} FROM numbers")  # noqa: S608


def rent_charges(url: str) -> list[Decimal]:
    async def work(factory: Any) -> list[Decimal]:
        async with factory() as session:
            rows = await session.scalars(
                select(WalletEntry.amount).where(WalletEntry.kind == LedgerKind.NUMBER)
            )
            return list(rows)

    return run_db(url, work)  # type: ignore[no-any-return]


def test_a_month_ends_on_the_same_day_or_the_last_day() -> None:
    assert renewals.next_month(date(2026, 11, 15)) == date(2026, 12, 15)
    assert renewals.next_month(date(2026, 12, 31)) == date(2027, 1, 31)
    assert renewals.next_month(date(2026, 1, 31)) == date(2026, 2, 28)
    assert renewals.next_month(date(2028, 1, 31)) == date(2028, 2, 29)
    assert renewals.today_ist(datetime(2026, 11, 14, 19, 0, tzinfo=UTC)) == date(2026, 11, 15)


def test_rent_comes_from_credits_once_per_month(api: TestClient, migrated_url: str) -> None:
    _, _, _, owner = rented(api, migrated_url, "2000")
    assert tick(migrated_url, at(DUE - timedelta(days=1)))["renewed"] == 0  # not due yet
    assert rent_charges(migrated_url) == []
    assert tick(migrated_url, at(DUE)) == {"renewed": 1, "grace": 0, "released": 0, "waiting": 0}
    assert rent_charges(migrated_url) == [Decimal("-649")]
    assert (number(migrated_url, "status::text"), str(number(migrated_url, "renews_on"))) == (
        "active", "2026-12-15",
    )  # fmt: skip
    for hour in (7, 12, 20):  # ticks later the same day, and the next days: nothing more is due
        assert tick(migrated_url, at(DUE, hour))["renewed"] == 0
    assert tick(migrated_url, at(DUE + timedelta(days=20)))["renewed"] == 0
    assert rent_charges(migrated_url) == [Decimal("-649")]
    assert Decimal(api.get("/wallet", headers=owner).json()["balance"]) == 2000 - 649


def test_a_period_already_charged_is_not_charged_again_after_a_crash(
    api: TestClient, migrated_url: str
) -> None:
    mine, number_id, _, _ = rented(api, migrated_url, "2000")

    mine_id = uuid.UUID(mine)

    async def go(factory: Any) -> None:
        async with factory() as session:
            await ledger.post(
                session, mine_id, LedgerKind.NUMBER, -649,
                ref_type=renewals.REF, ref_id=f"{number_id}:{DUE}",
            )  # fmt: skip
            await session.commit()

    run_db(migrated_url, go)
    assert tick(migrated_url, at(DUE))["renewed"] == 1
    assert rent_charges(migrated_url) == [
        Decimal("-649")
    ]  # one charge, though the tick ran after it
    assert str(number(migrated_url, "renews_on")) == "2026-12-15"


def test_extra_channels_are_rented_with_the_number(
    api: TestClient, migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AXON_EXTRA_CHANNEL_FEE", "100")
    rented(api, migrated_url, "2000")
    sql(migrated_url, "UPDATE numbers SET channels = 3")
    tick(migrated_url, at(DUE))
    assert rent_charges(migrated_url) == [Decimal("-849")]


def test_without_credits_it_falls_into_grace_and_keeps_working(
    api: TestClient, migrated_url: str, mailbox: Mailbox
) -> None:
    _, _, employee, owner = rented(api, migrated_url, "100")
    assert tick(migrated_url, at(DUE)) == {"renewed": 0, "grace": 1, "released": 0, "waiting": 0}
    assert number(migrated_url, "status::text") == "grace"
    assert str(number(migrated_url, "grace_until")) == "2026-11-22"
    assert str(number(migrated_url, "renews_on")) == "2026-11-15"  # still the unpaid month
    assert rent_charges(migrated_url) == []
    assert (
        sql(migrated_url, "SELECT status::text FROM employees WHERE id = :e", {"e": employee})
        == "live"
    )
    assert (
        sql(migrated_url, "SELECT number_id FROM employees WHERE id = :e", {"e": employee})
        is not None
    )
    notes = api.get("/notifications", headers=owner).json()["items"]
    assert [n["kind"] for n in notes] == ["number_grace"]
    assert len(mailbox.sent) == 1 and E164 in mailbox.sent[0]["subject"]
    for days in range(1, 7):  # every day of grace: still waiting, no new note, no new email
        assert tick(migrated_url, at(DUE + timedelta(days=days)))["waiting"] == 1
    assert (
        len(mailbox.sent) == 1
        and len(api.get("/notifications", headers=owner).json()["items"]) == 1
    )
    assert number(migrated_url, "status::text") == "grace"


def test_a_top_up_renews_a_number_in_grace_at_once(api: TestClient, migrated_url: str) -> None:
    mine, _, _, owner = rented(api, migrated_url, "100")
    tick(migrated_url, at(DUE))
    assert number(migrated_url, "status::text") == "grace"
    order = sql(
        migrated_url,
        "INSERT INTO payments (account_id, provider, provider_order_id, amount_inr, status)"
        " VALUES (:a, 'razorpay', 'order_1', 1000, 'created') RETURNING provider_order_id",
        {"a": mine},
    )

    async def pay(factory: Any) -> None:
        async with factory() as session:
            await payments.settle(session, order, "pay_1", now=at(DUE + timedelta(days=2)))
            await session.commit()

    run_db(migrated_url, pay)
    assert (number(migrated_url, "status::text"), number(migrated_url, "grace_until")) == (
        "active",
        None,
    )
    assert str(number(migrated_url, "renews_on")) == "2026-12-15"
    assert rent_charges(migrated_url) == [Decimal("-649")]
    assert Decimal(api.get("/wallet", headers=owner).json()["balance"]) == 100 + 1000 - 649


def test_credits_that_arrive_by_other_means_are_found_by_the_next_tick(
    api: TestClient, migrated_url: str
) -> None:
    mine, _, _, _ = rented(api, migrated_url, "100")
    tick(migrated_url, at(DUE))
    give_credits(migrated_url, mine, "700")  # an admin adjustment, say
    assert tick(migrated_url, at(DUE + timedelta(days=1)))["renewed"] == 1
    assert number(migrated_url, "status::text") == "active"
    assert rent_charges(migrated_url) == [Decimal("-649")]


def test_at_the_end_of_grace_it_is_released_and_only_the_employees_number_goes(
    api: TestClient, migrated_url: str, vobiz: VobizAccount, mailbox: Mailbox
) -> None:
    mine, _, _, owner = rented(api, migrated_url, "100")
    vobiz.owned.add(E164)
    sql(
        migrated_url,
        "INSERT INTO leads (account_id, phone, name) VALUES (:a, '+919876543210', 'Ravi')",
        {"a": mine},
    )
    tick(migrated_url, at(DUE))
    grace_ends = date(2026, 11, 22)
    assert (
        tick(migrated_url, at(grace_ends))["waiting"] == 1
    )  # the last day of grace is still grace
    assert vobiz.sent("DELETE", "/numbers") == []
    assert tick(migrated_url, at(grace_ends + timedelta(days=1))) == {
        "renewed": 0, "grace": 0, "released": 1, "waiting": 0,
    }  # fmt: skip
    assert [
        r.url.raw_path.decode().rsplit("/", 1)[-1] for r in vobiz.sent("DELETE", "/numbers")
    ] == ["%2B911400000001"]
    assert number(migrated_url, "status::text") == "released"
    row = sql(migrated_url, "SELECT status::text || coalesce(number_id::text, '-') FROM employees")
    assert row == "paused-"  # detached and paused
    assert (
        sql(migrated_url, "SELECT name FROM employees") == "Asha"
    )  # nothing else about it is lost
    assert sql(migrated_url, "SELECT count(*) FROM leads") == 1
    assert sql(migrated_url, "SELECT count(*) FROM employee_versions") >= 1
    kinds = [n["kind"] for n in api.get("/notifications", headers=owner).json()["items"]]
    assert sorted(kinds) == ["number_grace", "number_released"]
    assert len(mailbox.sent) == 2
    assert tick(migrated_url, at(grace_ends + timedelta(days=9))) == {
        "renewed": 0, "grace": 0, "released": 0, "waiting": 0,
    }  # fmt: skip  # a released number is never touched or charged again
    assert rent_charges(migrated_url) == []


def test_a_carrier_that_cannot_release_is_asked_again_on_the_next_tick(
    api: TestClient, migrated_url: str, vobiz: VobizAccount
) -> None:
    rented(api, migrated_url, "0")
    vobiz.owned.add(E164)
    tick(migrated_url, at(DUE))
    late = at(DUE + timedelta(days=8))
    vobiz.fail_release = True
    assert tick(migrated_url, late)["waiting"] == 1
    assert number(migrated_url, "status::text") == "grace"  # kept, not lost
    vobiz.fail_release = False
    assert tick(migrated_url, late + timedelta(minutes=10))["released"] == 1
    assert number(migrated_url, "status::text") == "released"


def test_without_carrier_keys_a_lapsed_number_waits_rather_than_vanishing(
    api: TestClient, migrated_url: str
) -> None:
    rented(api, migrated_url, "0")
    tick(migrated_url, at(DUE))
    assert tick(migrated_url, at(DUE + timedelta(days=8)))["waiting"] == 1
    assert number(migrated_url, "status::text") == "grace"


def test_four_months_of_random_top_ups_never_double_charge_or_overdraw(
    api: TestClient, migrated_url: str, vobiz: VobizAccount
) -> None:
    mine, _, _, _ = rented(api, migrated_url, "700")
    vobiz.owned.add(E164)
    rng = random.Random(11)  # noqa: S311 - a repeatable test sequence
    day, topped = DUE, 700
    for _ in range(120):
        day += timedelta(days=1)
        if rng.random() < 0.06:
            give_credits(migrated_url, mine, "700")
            topped += 700
        tick(migrated_url, at(day))
        if number(migrated_url, "status::text") == "released":
            break
    charges = rent_charges(migrated_url)

    async def audit(factory: Any) -> tuple[int, int, Decimal, Decimal]:
        async with factory() as session:
            refs = await session.scalar(
                select(func.count(func.distinct(WalletEntry.ref_id))).where(
                    WalletEntry.kind == LedgerKind.NUMBER
                )
            )
            total = await session.scalar(
                select(func.count()).where(WalletEntry.kind == LedgerKind.NUMBER)
            )
            balance = await ledger.balance(session, mine)  # type: ignore[arg-type]
            summed = await session.scalar(
                select(func.coalesce(func.sum(WalletEntry.amount), 0)).where(
                    WalletEntry.account_id == mine
                )
            )
            return int(refs or 0), int(total or 0), balance, Decimal(summed or 0)

    refs, total, balance, summed = run_db(migrated_url, audit)
    assert refs == total == len(charges) > 0  # every month charged under its own reference
    assert balance == summed == topped - 649 * len(charges) and balance >= 0
