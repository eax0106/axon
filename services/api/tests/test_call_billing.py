"""Calls are charged from the carrier's own record, once, at the rate of the tier they ran on."""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import count
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.billing import alerts, metering
from app.models import Call, CallEvent, Notification, WalletEntry
from app.providers.email.resend import ResendEmail
from app.providers.telephony.vobiz import VobizTelephony

from .conftest import sql
from .helpers import account_id, add_call, live_employee, run_db, seed, signup

NOW = datetime(2026, 11, 2, 5, 30, tzinfo=UTC)
ENDED = NOW - timedelta(minutes=5)
NUMBERS = count(1)  # each employee needs a number of its own


class Cdr:
    """Vobiz's call detail records, keyed by the carrier's call id."""

    def __init__(self) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.down = False
        self.asked: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        carrier_id = request.url.path.rsplit("/", 1)[-1]
        self.asked.append(carrier_id)
        if self.down:
            return httpx.Response(503)
        record = self.records.get(carrier_id)
        return httpx.Response(404) if record is None else httpx.Response(200, json=record)


@pytest.fixture
def api(db_client: TestClient, migrated_url: str) -> TestClient:
    seed(migrated_url)
    return db_client


@pytest.fixture
def cdr(monkeypatch: pytest.MonkeyPatch) -> tuple[Cdr, VobizTelephony]:
    monkeypatch.setenv("VOBIZ_AUTH_ID", "MA_TEST")
    monkeypatch.setenv("VOBIZ_AUTH_TOKEN", "token")
    fake = Cdr()
    return fake, VobizTelephony(transport=httpx.MockTransport(fake.handler))


def finished_call(
    url: str, api: TestClient, owner: dict[str, str], *, tier: str | None = "value", **cols: Any
) -> tuple[Any, str]:
    """A completed instant call with a carrier id; returns (call id, carrier id)."""
    employee = live_employee(api, url, owner, number=f"+9114{next(NUMBERS):08d}")
    account = sql(url, "SELECT account_id FROM employees WHERE id = :e", {"e": employee})
    cols.setdefault("ended_at", ENDED)
    call = add_call(url, account, employee, **cols)
    carrier_id = f"leg-{str(call)[:8]}"
    sql(
        url,
        "UPDATE calls SET carrier_leg_id = :c, carrier_call_id = :c, voice_tier = :t WHERE id = :i",
        {"c": carrier_id, "t": tier, "i": call},
    )
    return call, carrier_id


def bill(url: str, telephony: VobizTelephony, now: datetime = NOW) -> dict[str, int]:
    counts: dict[str, int] = run_db(url, lambda f: metering.bill_pending(f, telephony, now))
    return counts


def balance(url: str, owner_account: str) -> Decimal:
    return Decimal(
        str(sql(url, "SELECT credit_balance FROM accounts WHERE id = :a", {"a": owner_account}))
    )


def test_a_call_is_charged_for_its_talk_seconds_at_its_tiers_rate(
    api: TestClient, migrated_url: str, cdr: tuple[Cdr, VobizTelephony]
) -> None:
    fake, telephony = cdr
    owner = signup(api)
    mine = account_id(api, owner)
    call, carrier_id = finished_call(migrated_url, api, owner, tier="premium")
    fake.records[carrier_id] = {"billsec": 90, "duration": 100, "hangup_cause": "NORMAL_CLEARING"}
    assert bill(migrated_url, telephony) == {"billed": 1, "free": 0, "reconcile": 0, "waiting": 0}
    # Premium is 7 credits a minute: 90 s is 10.5. The account started with 50 free credits.
    assert balance(migrated_url, mine) == Decimal("39.5")

    async def read(factory: Any) -> Call:
        async with factory() as session:
            return await session.get(Call, call)  # type: ignore[no-any-return]

    row = run_db(migrated_url, read)
    assert row.billing_status == "billed" and row.billed_seconds == 90
    assert row.credits_charged == Decimal("10.5")


def test_billing_twice_charges_once(
    api: TestClient, migrated_url: str, cdr: tuple[Cdr, VobizTelephony]
) -> None:
    fake, telephony = cdr
    owner = signup(api)
    mine = account_id(api, owner)
    _, carrier_id = finished_call(migrated_url, api, owner)
    fake.records[carrier_id] = {"billsec": 60, "duration": 70, "hangup_cause": "NORMAL_CLEARING"}
    assert bill(migrated_url, telephony)["billed"] == 1
    assert bill(migrated_url, telephony) == {"billed": 0, "free": 0, "reconcile": 0, "waiting": 0}
    assert balance(migrated_url, mine) == Decimal("46.5")  # 50 - 3.5
    entries = sql(
        migrated_url,
        "SELECT count(*) FROM wallet_ledger WHERE account_id = :a AND kind = 'call'",
        {"a": mine},
    )
    assert entries == 1


def test_a_call_nobody_answered_is_free(
    api: TestClient, migrated_url: str, cdr: tuple[Cdr, VobizTelephony]
) -> None:
    fake, telephony = cdr
    owner = signup(api)
    mine = account_id(api, owner)
    call, carrier_id = finished_call(migrated_url, api, owner, status="no_answer")
    fake.records[carrier_id] = {"billsec": 0, "duration": 30, "hangup_cause": "NO_ANSWER"}
    assert bill(migrated_url, telephony)["free"] == 1
    assert balance(migrated_url, mine) == Decimal(50)
    assert (
        sql(migrated_url, "SELECT billing_status FROM calls WHERE id = :i", {"i": call}) == "free"
    )


def test_the_carrier_record_decides_never_what_the_call_row_says(
    api: TestClient, migrated_url: str, cdr: tuple[Cdr, VobizTelephony]
) -> None:
    """Our own duration column (set from an unsigned callback) is ignored."""
    fake, telephony = cdr
    owner = signup(api)
    mine = account_id(api, owner)
    _, carrier_id = finished_call(migrated_url, api, owner, duration_s=3600)
    fake.records[carrier_id] = {"billsec": 6, "duration": 9, "hangup_cause": "NORMAL_CLEARING"}
    bill(migrated_url, telephony)
    assert balance(migrated_url, mine) == Decimal("49.65")  # 6 s at 3.5 a minute


def test_no_carrier_record_yet_waits_and_after_a_day_is_flagged_never_charged(
    api: TestClient, migrated_url: str, cdr: tuple[Cdr, VobizTelephony]
) -> None:
    _, telephony = cdr
    owner = signup(api)
    mine = account_id(api, owner)
    call, _ = finished_call(migrated_url, api, owner)
    assert bill(migrated_url, telephony)["waiting"] == 1
    assert bill(migrated_url, telephony, NOW + timedelta(hours=23))["waiting"] == 1
    assert bill(migrated_url, telephony, NOW + timedelta(hours=25))["reconcile"] == 1
    assert balance(migrated_url, mine) == Decimal(50)
    assert (
        sql(migrated_url, "SELECT billing_status FROM calls WHERE id = :i", {"i": call})
        == "reconcile"
    )

    async def events(factory: Any) -> int:
        async with factory() as session:
            return int(
                await session.scalar(
                    select(func.count()).where(
                        CallEvent.call_id == call, CallEvent.type == "billing_reconcile"
                    )
                )
                or 0
            )

    assert run_db(migrated_url, events) == 1
    assert bill(migrated_url, telephony, NOW + timedelta(hours=26))["reconcile"] == 0


def test_a_carrier_outage_leaves_the_call_for_the_next_tick(
    api: TestClient, migrated_url: str, cdr: tuple[Cdr, VobizTelephony]
) -> None:
    fake, telephony = cdr
    owner = signup(api)
    _, carrier_id = finished_call(migrated_url, api, owner)
    fake.records[carrier_id] = {"billsec": 60, "duration": 70, "hangup_cause": "NORMAL_CLEARING"}
    fake.down = True
    assert bill(migrated_url, telephony)["waiting"] == 1
    fake.down = False
    assert bill(migrated_url, telephony)["billed"] == 1


def test_fresh_test_and_unplaced_calls_are_not_looked_at(
    api: TestClient, migrated_url: str, cdr: tuple[Cdr, VobizTelephony]
) -> None:
    fake, telephony = cdr
    owner = signup(api)
    finished_call(migrated_url, api, owner, ended_at=NOW - timedelta(seconds=5))  # too fresh
    finished_call(migrated_url, api, owner, is_test=True)
    finished_call(migrated_url, api, owner, status="queued")
    assert bill(migrated_url, telephony) == {"billed": 0, "free": 0, "reconcile": 0, "waiting": 0}
    assert fake.asked == []


def test_a_call_with_no_recorded_tier_is_charged_at_its_employees_voice(
    api: TestClient, migrated_url: str, cdr: tuple[Cdr, VobizTelephony]
) -> None:
    fake, telephony = cdr
    owner = signup(api)
    mine = account_id(api, owner)
    _, carrier_id = finished_call(migrated_url, api, owner, tier=None)
    fake.records[carrier_id] = {"billsec": 60, "duration": 70, "hangup_cause": "NORMAL_CLEARING"}
    bill(migrated_url, telephony)
    spent = Decimal(50) - balance(migrated_url, mine)
    assert spent == Decimal("3.5")  # no voice chosen yet: the Value rate


def test_a_call_that_already_happened_is_charged_even_into_the_red(
    api: TestClient, migrated_url: str, cdr: tuple[Cdr, VobizTelephony]
) -> None:
    fake, telephony = cdr
    owner = signup(api)
    mine = account_id(api, owner)
    sql(migrated_url, "UPDATE accounts SET credit_balance = 1 WHERE id = :a", {"a": mine})
    _, carrier_id = finished_call(migrated_url, api, owner, tier="premium")
    fake.records[carrier_id] = {"billsec": 90, "duration": 95, "hangup_cause": "NORMAL_CLEARING"}
    bill(migrated_url, telephony)
    assert balance(migrated_url, mine) == Decimal("-9.5")


def test_dropping_under_the_threshold_notes_the_account_and_emails_once_a_day(
    api: TestClient,
    migrated_url: str,
    cdr: tuple[Cdr, VobizTelephony],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake, telephony = cdr
    sent: list[dict[str, Any]] = []

    def resend(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "email-1"})

    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("EMAIL_FROM", "billing@example.in")
    monkeypatch.setattr(
        alerts, "require", lambda _kind: ResendEmail(transport=httpx.MockTransport(resend))
    )
    owner = signup(api)
    mine = account_id(api, owner)
    sql(migrated_url, "UPDATE accounts SET credit_balance = 52 WHERE id = :a", {"a": mine})
    _, first = finished_call(migrated_url, api, owner)
    fake.records[first] = {"billsec": 60, "duration": 70, "hangup_cause": "NORMAL_CLEARING"}
    bill(migrated_url, telephony)  # 52 -> 48.5, under 50
    assert len(sent) == 1 and sent[0]["to"] == ["owner@example.com"]
    _, second = finished_call(migrated_url, api, owner)
    fake.records[second] = {"billsec": 60, "duration": 70, "hangup_cause": "NORMAL_CLEARING"}
    bill(migrated_url, telephony)  # already under: no second note and no second email
    assert len(sent) == 1

    async def notes(factory: Any) -> int:
        async with factory() as session:
            return int(
                await session.scalar(select(func.count()).where(Notification.kind == "low_balance"))
                or 0
            )

    assert run_db(migrated_url, notes) == 1
    total = run_db(
        migrated_url,
        lambda f: _count(f, WalletEntry),
    )
    assert total >= 3  # signup bonus, two calls


async def _count(factory: Any, model: Any) -> int:
    async with factory() as session:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)
