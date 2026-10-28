"""Admin console: system health, revenue, announcements and alerts."""

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.admin import reports
from app.billing import ledger
from app.models import LedgerKind
from app.providers import health

from .conftest import sql
from .helpers import account_id, add_call, run_db, signup, staff


@pytest.fixture
def redis_url(monkeypatch: pytest.MonkeyPatch) -> str | None:
    """The API's Redis: the test one when set, else a port where nothing listens."""
    url = os.environ.get("AXON_TEST_REDIS_URL") or "redis://127.0.0.1:1/0"
    monkeypatch.setenv("REDIS_URL", url)
    return os.environ.get("AXON_TEST_REDIS_URL")


def post(url: str, account: Any, kind: LedgerKind, amount: str, ago: timedelta) -> None:
    async def work(factory: Any) -> None:
        async with factory() as session:
            await ledger.post(
                session, uuid.UUID(str(account)), kind, Decimal(amount),
                ref_type="test", ref_id=uuid.uuid4().hex, allow_overdraw=True,
            )  # fmt: skip
            await session.commit()

    run_db(url, work)
    latest = "(SELECT max(id) FROM wallet_ledger)"
    sql(
        url,
        f"UPDATE wallet_ledger SET created_at = :at WHERE id = {latest}",  # noqa: S608
        {"at": datetime.now(UTC) - ago},
    )


def beat(url: str, at: datetime) -> None:
    run_db(url, lambda factory: reports.beat(factory, at))


def test_system_health_reports_the_database_redis_the_worker_and_the_queues(
    redis_url: str | None, db_client: TestClient, migrated_url: str
) -> None:
    admin = staff(db_client, migrated_url)
    account = sql(migrated_url, "SELECT account_id FROM users")
    add_call(migrated_url, account, status="queued")
    sql(migrated_url, "UPDATE calls SET scheduled_for = now() - interval '1 minute'")
    add_call(migrated_url, account, status="completed", analysis_status="pending")

    body = db_client.get("/admin/system", headers=admin).json()
    assert body["database"]["ok"] is True
    assert body["redis"]["ok"] is (redis_url is not None)
    assert body["worker"] == {"last_heartbeat": None, "silent": True}
    assert body["queues"] == {
        "calls_due": 1,
        "analysis_waiting": 1,
        "webhooks_waiting": 0,
        "calls_to_reconcile": 0,
    }
    beat(migrated_url, datetime.now(UTC))
    worker = db_client.get("/admin/system", headers=admin).json()["worker"]
    assert worker["silent"] is False and worker["last_heartbeat"] is not None


def test_revenue_per_day_splits_money_in_from_what_was_used_with_cost_and_margin(
    db_client: TestClient, migrated_url: str
) -> None:
    owner = signup(db_client)
    admin = staff(db_client, migrated_url)
    account = account_id(db_client, owner)
    today = timedelta(0)
    post(migrated_url, account, LedgerKind.TOPUP, "1000", today)
    post(migrated_url, account, LedgerKind.CALL, "-12.50", today)
    post(migrated_url, account, LedgerKind.NUMBER, "-600", today)
    post(migrated_url, account, LedgerKind.AI_USE, "-2", today)
    post(migrated_url, account, LedgerKind.REFUND, "100", today)
    post(migrated_url, account, LedgerKind.TOPUP, "5000", timedelta(days=40))  # outside
    call = add_call(migrated_url, account, status="completed", ended_at=datetime.now(UTC))
    meters = [{"kind": "stt", "vendor": "sarvam", "unit": "audio_seconds", "amount": 600}]
    sql(
        migrated_url,
        "INSERT INTO call_events (call_id, type, data) VALUES (:c, 'usage', CAST(:d AS jsonb))",
        {"c": call, "d": json.dumps({"meters": meters})},
    )
    rate = {"kind": "stt", "vendor": "sarvam", "unit": "audio_seconds", "inr_per_unit": "0.01"}
    db_client.put("/admin/provider-rates", json=rate, headers=admin)

    body = db_client.get("/admin/revenue", params={"days": 30}, headers=admin).json()
    (day,) = body["items"]  # the signup bonuses are free credits, not money in or use
    figures = {k: Decimal(str(v)) for k, v in day.items() if k != "day"}
    assert figures == {
        "topups": Decimal("1000"),
        "calls": Decimal("12.50"),
        "numbers": Decimal("600"),
        "ai": Decimal("2"),
        "refunds": Decimal("100"),
        "provider_cost": Decimal("6.00"),
        "used": Decimal("514.50"),
        "margin": Decimal("508.50"),
    }
    assert day["day"] == (datetime.now(UTC) + timedelta(hours=5, minutes=30)).date().isoformat()


def test_an_announcement_reaches_every_accounts_bell(
    db_client: TestClient, migrated_url: str
) -> None:
    people = [signup(db_client, email=f"o{i}@example.com", account=f"A{i}") for i in range(3)]
    admin = staff(db_client, migrated_url)
    note = {"title": "Planned upkeep", "body": "Calls pause 02:00-02:15 IST on Sunday."}
    sent = db_client.post("/admin/announcements", json=note, headers=admin)
    assert sent.json() == {"accounts": 4}  # the three accounts and staff's own
    for headers in people:
        (item,) = db_client.get("/notifications", headers=headers).json()["items"]
        assert (item["kind"], item["title"], item["read"]) == (
            "announcement",
            "Planned upkeep",
            False,
        )
    assert sql(migrated_url, "SELECT count(*) FROM audit_log WHERE action = 'announcement'") == 1
    short = db_client.post("/admin/announcements", json={"title": "x", "body": "y"}, headers=admin)
    assert short.status_code == 422


def test_alerts_list_what_needs_a_person(db_client: TestClient, migrated_url: str) -> None:
    owner = signup(db_client)
    admin = staff(db_client, migrated_url)
    assert db_client.get("/admin/alerts", headers=admin).json() == [
        {"kind": "worker_silent", "detail": "the worker was last seen never"}
    ]

    async def failing(factory: Any) -> None:
        async with factory() as session:
            for _ in range(3):
                health.record(session, "tts", "cartesia", ok=False, at=datetime.now(UTC))
            await session.commit()

    run_db(migrated_url, failing)
    db_client.put(
        "/admin/provider-balances/sarvam",
        json={"balance_inr": "50", "alert_below_inr": "100"},
        headers=admin,
    )
    sql(
        migrated_url,
        "INSERT INTO numbers (account_id, provider, e164, number_type, status)"
        " VALUES (:a, 'vobiz', '+911400000010', 'regular', 'reconcile')",
        {"a": account_id(db_client, owner)},
    )
    beat(migrated_url, datetime.now(UTC) - timedelta(minutes=10))
    kinds = [a["kind"] for a in db_client.get("/admin/alerts", headers=admin).json()]
    assert kinds == [
        "provider_unhealthy",
        "provider_balance_low",
        "numbers_to_reconcile",
        "worker_silent",
    ]
    beat(migrated_url, datetime.now(UTC))
    alerts = db_client.get("/admin/alerts", headers=admin).json()
    assert "worker_silent" not in [a["kind"] for a in alerts]
    assert alerts[0]["detail"] == "tts vendor cartesia is failing"
