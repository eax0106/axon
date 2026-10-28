"""Credit policy: free credits, no dialing at zero, the hourly cap, the low-balance alert and the
fee for AI help, all through the ledger."""

import base64
import json
import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.billing import alerts, ledger
from app.models import LedgerKind, Notification, WalletEntry
from app.numbers import renewals
from app.providers.speech import common
from app.providers.telephony.vobiz import VobizTelephony

from .conftest import sql
from .dialing import NOW, Carrier, lead_in, tick
from .helpers import account_id, live_employee, run_db, seed, signup
from .test_post_call_job import model_reply

FEE = Decimal("0.2")
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + bytes(20)


class Vendors:
    """Gemini and Sarvam answering for the AI endpoints; `down` makes every request fail."""

    def __init__(self) -> None:
        self.down = False
        self.text = json.dumps({"questions": ["Which cities?"]})

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            return httpx.Response(500)
        if request.url.host == "api.sarvam.ai":
            return httpx.Response(200, json={"audios": [base64.b64encode(WAV).decode()]})
        body = {"candidates": [{"content": {"role": "model", "parts": [{"text": self.text}]}}]}
        return httpx.Response(200, json=body)


@pytest.fixture
def api(db_client: TestClient, migrated_url: str, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    seed(migrated_url)
    monkeypatch.setenv("AXON_ENGINE_PUBLIC_URL", "https://engine.example.in")
    monkeypatch.setenv("AXON_API_PUBLIC_URL", "https://api.example.in")
    return db_client


@pytest.fixture
def carrier(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Carrier, VobizTelephony]]:
    monkeypatch.setenv("VOBIZ_AUTH_ID", "MA_TEST")
    monkeypatch.setenv("VOBIZ_AUTH_TOKEN", "token")
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")  # the speech legs: no call starts without them
    fake = Carrier()
    yield fake, VobizTelephony(transport=httpx.MockTransport(fake.handler))


@pytest.fixture
def vendors(monkeypatch: pytest.MonkeyPatch) -> Vendors:
    for key in ("GEMINI_API_KEY", "SARVAM_API_KEY"):
        monkeypatch.setenv(key, "test-key")
    fake = Vendors()
    transport = httpx.MockTransport(fake.handler)
    monkeypatch.setattr(
        common.VendorHealth,
        "client",
        lambda self, timeout=60.0: httpx.AsyncClient(transport=transport),
    )
    return fake


def balance(client: TestClient, owner: dict[str, str]) -> Decimal:
    return Decimal(client.get("/wallet", headers=owner).json()["balance"])


def entries(url: str, account: str, kind: str) -> list[Decimal]:
    async def work(factory: Any) -> list[Decimal]:
        async with factory() as session:
            rows = await session.scalars(
                select(WalletEntry.amount).where(
                    WalletEntry.account_id == account, WalletEntry.kind == LedgerKind(kind)
                )
            )
            return list(rows)

    return run_db(url, work)  # type: ignore[no-any-return]


# --- Free credits ------------------------------------------------------------------------------


def test_every_account_gets_fifty_free_credits_once(api: TestClient, migrated_url: str) -> None:
    owner = signup(api)
    assert balance(api, owner) == 50
    login = api.post(
        "/auth/login", json={"email": "owner@example.com", "password": "correct horse battery"}
    )
    assert login.status_code == 200 and balance(api, owner) == 50  # logging in is not a new bonus
    other = signup(api, "b@example.com", "B")
    assert balance(api, other) == 50
    assert entries(migrated_url, account_id(api, owner), "bonus") == [Decimal(50)]
    assert api.get("/billing/rates", headers=owner).json()["free_signup_credits"] == "50"


# --- No dialing at zero, and the hourly cap ----------------------------------------------------


def queue_call(api: TestClient, url: str) -> tuple[str, dict[str, str]]:
    owner = signup(api)
    employee = live_employee(api, url, owner)
    lead_in(url, employee, "9876543210", name="Ravi")
    return employee, owner


def call_events(url: str) -> list[str]:
    return [
        str(e)
        for e in sql(url, "SELECT coalesce(array_agg(type ORDER BY id), '{}') FROM call_events")
    ]


def test_dialing_waits_while_the_balance_is_zero_and_resumes_after_a_top_up(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    _, owner = queue_call(api, migrated_url)
    mine = account_id(api, owner)
    sql(migrated_url, "UPDATE accounts SET credit_balance = 0 WHERE id = :a", {"a": mine})
    assert tick(migrated_url, adapter, NOW + timedelta(seconds=10))[0].outcome == "rescheduled"
    assert fake.placed == []
    assert "blocked_credits" in call_events(migrated_url)
    reason = sql(
        migrated_url, "SELECT data->>'reason' FROM call_events WHERE type = 'blocked_credits'"
    )
    assert reason == "no credits left: top up to keep calling"
    assert sql(migrated_url, "SELECT status::text FROM calls") == "queued"  # kept, not failed
    sql(migrated_url, "UPDATE accounts SET credit_balance = 10 WHERE id = :a", {"a": mine})
    assert [p.outcome for p in tick(migrated_url, adapter, NOW + timedelta(minutes=10))] == [
        "dialed"
    ]


def seed_spend(url: str, account: str, amount: str, minutes_ago: int) -> None:
    sql(
        url,
        "INSERT INTO wallet_ledger (account_id, kind, amount, balance_after, created_at)"
        " VALUES (:a, 'call', :x, 0, :t)",
        {"a": account, "x": -Decimal(amount), "t": NOW - timedelta(minutes=minutes_ago)},
    )


def test_the_hourly_spend_cap_holds_dialing_until_the_hour_has_passed(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    _, owner = queue_call(api, migrated_url)
    mine = account_id(api, owner)
    saved = api.put("/billing/settings", json={"spend_cap_per_hour": "10"}, headers=owner)
    assert saved.status_code == 200 and saved.json()["spend_cap_per_hour"] == "10.0000"
    seed_spend(migrated_url, mine, "6", 30)
    seed_spend(migrated_url, mine, "4", 20)  # 10 spent in the last hour: at the cap
    assert tick(migrated_url, adapter, NOW + timedelta(seconds=10))[0].outcome == "rescheduled"
    assert fake.placed == []
    reason = sql(
        migrated_url, "SELECT data->>'reason' FROM call_events WHERE type = 'blocked_credits'"
    )
    assert reason == "the hourly spend cap of 10.00 credits has been reached"
    # Spend from before the last hour does not count: 40 minutes later only the 4 is inside it.
    assert [p.outcome for p in tick(migrated_url, adapter, NOW + timedelta(minutes=45))] == [
        "dialed"
    ]


def test_the_cap_can_be_removed_and_is_owner_only(api: TestClient, migrated_url: str) -> None:
    owner = signup(api)
    api.put("/billing/settings", json={"spend_cap_per_hour": "10"}, headers=owner)
    removed = api.put("/billing/settings", json={"spend_cap_per_hour": None}, headers=owner)
    assert removed.json()["spend_cap_per_hour"] is None
    untouched = api.put("/billing/settings", json={"legal_name": "Acme Pvt Ltd"}, headers=owner)
    assert untouched.json()["details"] == {"legal_name": "Acme Pvt Ltd"}
    member_id = sql(
        migrated_url,
        "INSERT INTO users (account_id, email, password_hash, role)"
        " VALUES (:a, 'm@example.com', 'x', 'member') RETURNING id",
        {"a": account_id(api, owner)},
    )
    from app.auth import issue_token
    from app.models import User

    member = {"Authorization": f"Bearer {issue_token(User(id=member_id))}"}
    assert (
        api.put("/billing/settings", json={"spend_cap_per_hour": "1"}, headers=member).status_code
        == 403
    )
    assert (
        api.get("/wallet", headers=member).status_code == 200
    )  # but anyone in the account can look


# --- Low-balance alert -------------------------------------------------------------------------


def test_the_low_balance_note_comes_on_each_crossing_and_the_email_once_a_day(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    mine = account_id(api, owner)
    sql(migrated_url, "UPDATE accounts SET credit_balance = 55 WHERE id = :a", {"a": mine})

    def post(amount: str, at: Any) -> None:
        async def work(factory: Any) -> None:
            async with factory() as session:
                kind = LedgerKind.TOPUP if Decimal(amount) > 0 else LedgerKind.ADJUSTMENT
                await ledger.post(session, uuid.UUID(mine), kind, amount, now=at)
                await session.commit()

        run_db(migrated_url, work)

    def pending() -> bool:
        flag = sql(
            migrated_url,
            "SELECT low_balance_email_pending FROM accounts WHERE id = :a",
            {"a": mine},
        )
        return bool(flag)

    post("-10", NOW)  # 55 -> 45: under 50 for the first time, an email is due
    assert pending() is True
    assert run_db(migrated_url, alerts.send_pending) == 1 and pending() is False
    post("-15", NOW)  # already under 50: nothing new to say
    assert pending() is False
    post("20", NOW)  # 30 -> 50, back to the threshold
    post("-10", NOW + timedelta(hours=2))  # crossed again, but an email went out today
    assert pending() is False
    post("20", NOW)
    post("-20", NOW + timedelta(hours=25))  # a day later it may email again
    assert pending() is True

    async def notes(factory: Any) -> int:
        async with factory() as session:
            return len(
                list(
                    await session.scalars(
                        select(Notification).where(Notification.kind == "low_balance")
                    )
                )
            )

    assert run_db(migrated_url, notes) == 3  # the bell has one per crossing
    wallet = api.get("/wallet", headers=owner).json()
    assert wallet["low"] is True  # 40 now
    sql(migrated_url, "UPDATE accounts SET credit_balance = 50 WHERE id = :a", {"a": mine})
    assert api.get("/wallet", headers=owner).json()["low"] is False  # exactly the threshold


def test_every_kind_of_spend_raises_the_low_balance_alert_not_only_calls(
    api: TestClient, migrated_url: str, vendors: Vendors
) -> None:
    owner = signup(api)
    mine = account_id(api, owner)

    def low_notes() -> int:
        return int(
            sql(migrated_url, "SELECT count(*) FROM notifications WHERE kind = 'low_balance'")
        )

    def reset(balance: str) -> None:
        sql(
            migrated_url,
            "UPDATE accounts SET credit_balance = :b, low_balance_emailed_at = NULL WHERE id = :a",
            {"a": mine, "b": balance},
        )

    reset("50.1")  # AI help: 0.2 takes it under 50
    brief = {"brief": "Call new leads.", "channel": "instant", "language": "en"}
    assert api.post("/ai/brief-questions", json=brief, headers=owner).status_code == 200
    assert low_notes() == 1
    reset("50")  # rent: a number's monthly fee
    sql(
        migrated_url,
        "INSERT INTO numbers (account_id, provider, e164, number_type, status, renews_on,"
        " monthly_fee) VALUES (:a, 'vobiz', '+919100000099', 'regular', 'active', :d, 1)",
        {"a": mine, "d": date(2026, 1, 1)},
    )
    run_db(migrated_url, lambda f: renewals.renew_due(f, NOW))
    assert low_notes() == 2
    assert sql(
        migrated_url, "SELECT low_balance_email_pending FROM accounts WHERE id = :a", {"a": mine}
    )


# --- The fee for AI help -----------------------------------------------------------------------


def test_each_kind_of_ai_help_costs_the_fee_through_the_ledger(
    api: TestClient, migrated_url: str, vendors: Vendors
) -> None:
    owner = signup(api)
    mine = account_id(api, owner)
    employee = live_employee(api, migrated_url, owner)
    voice = api.get("/voices?tier=value&language=te", headers=owner).json()[0]["id"]
    brief = {
        "brief": "Call new leads from my solar business.",
        "channel": "instant",
        "language": "en",
    }
    spent = Decimal(0)
    chat = {"messages": [{"role": "user", "content": "hi"}]}
    for path, body in (
        ("/ai/brief-questions", brief),  # the builder
        (f"/employees/{employee}/chat", chat),  # the chat sandbox
        (f"/voices/{voice}/preview?language=te", None),  # voice preview
    ):
        response = (
            api.post(path, json=body, headers=owner) if body else api.post(path, headers=owner)
        )
        assert response.status_code == 200
        spent += FEE
        assert balance(api, owner) == 50 - spent
    assert entries(migrated_url, mine, "ai_use") == [-FEE] * 3


def test_analysis_costs_the_fee_once_per_call_even_when_it_is_run_again(
    api: TestClient, migrated_url: str, vendors: Vendors
) -> None:
    from .test_post_call_job import NOW, make_call, process, setup

    employee, owner = setup(api, migrated_url)
    mine = account_id(api, owner)
    call = make_call(migrated_url, employee)
    vendors.down = True  # the analysis fails, retries included: nothing delivered, nothing charged
    for minutes in (0, 2, 12):
        assert process(migrated_url, NOW + timedelta(minutes=minutes)) == 1
    assert sql(migrated_url, "SELECT analysis_status FROM calls WHERE id = :c", {"c": call}) == (
        "failed"
    )
    assert balance(api, owner) == 50
    asked = api.post(f"/calls/{call}/reanalyze", headers=owner)
    assert asked.status_code == 202
    assert balance(api, owner) == 50  # asking is free: the fee is for the analysis itself
    vendors.down = False
    vendors.text = model_reply()
    assert process(migrated_url, NOW + timedelta(minutes=13)) == 1
    assert balance(api, owner) == 50 - FEE  # one fee in all, not one for the request and one more
    assert len(entries(migrated_url, mine, "ai_use")) == 1


def test_help_is_refused_with_402_at_zero_and_a_failed_request_gets_its_fee_back(
    api: TestClient, migrated_url: str, vendors: Vendors
) -> None:
    owner = signup(api)
    mine = account_id(api, owner)
    brief = {
        "brief": "Call new leads from my solar business.",
        "channel": "instant",
        "language": "en",
    }
    vendors.down = True
    failed = api.post("/ai/brief-questions", json=brief, headers=owner)
    assert failed.status_code in (500, 502, 503)
    assert balance(api, owner) == 50  # charged, then given back
    assert entries(migrated_url, mine, "ai_use") == [-FEE]
    assert entries(migrated_url, mine, "refund") == [FEE]
    vendors.down = False
    sql(migrated_url, "UPDATE accounts SET credit_balance = 0 WHERE id = :a", {"a": mine})
    refused = api.post("/ai/brief-questions", json=brief, headers=owner)
    assert refused.status_code == 402 and refused.json()["error"] == "insufficient_credits"
    assert Decimal(refused.json()["needed"]) == FEE


def test_the_analysis_fee_never_blocks_a_finished_analysis(
    api: TestClient, migrated_url: str, vendors: Vendors
) -> None:
    from .test_post_call_job import make_call, process, row, setup

    vendors.text = model_reply()
    employee, owner = setup(api, migrated_url)
    sql(
        migrated_url,
        "UPDATE accounts SET credit_balance = 0 WHERE id = :a",
        {"a": account_id(api, owner)},
    )
    call = make_call(migrated_url, employee)
    assert process(migrated_url) == 1
    assert row(migrated_url, call, "analysis_status") == "done"
    assert balance(api, owner) == -FEE  # the work was done, so it is recorded as owed
