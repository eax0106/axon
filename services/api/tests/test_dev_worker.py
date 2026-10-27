"""The worker only keeps the clock for the developer webhooks: the ticks call the tested
functions of app.developer."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from worker import main as worker

from .conftest import sql
from .developer_support import Receiver, deliveries, make_webhook
from .helpers import account_id, add_call, add_lead, live_employee, signup
from .test_worker import run_ticks


def test_the_webhook_jobs_are_scheduled_often_and_the_cleanup_hourly() -> None:
    jobs = {job.name: job for job in worker.WorkerSettings.cron_jobs}
    send = jobs["cron:webhook_tick"]
    assert send.second == set(range(2, 60, 5)) and send.minute is None  # every few seconds
    clean = jobs["cron:webhook_prune_tick"]
    assert clean.minute == 17 and clean.second == 50  # once an hour
    assert send.run_at_startup is False and clean.run_at_startup is False


def test_a_tick_announces_a_settled_call_and_sends_it(
    api: TestClient, migrated_url: str, receiver: type[Receiver], monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = signup(api)
    employee = live_employee(api, migrated_url, owner)
    account = account_id(api, owner)
    make_webhook(api, owner, f"{receiver.base}/hook", ["call.not_connected"])
    now = datetime.now(UTC)
    lead = add_lead(migrated_url, account, "+919876543210")
    add_call(
        migrated_url, account, employee, lead, status="no_answer",
        created_at=now - timedelta(minutes=2), ended_at=now - timedelta(minutes=1),
    )  # fmt: skip

    (count,) = run_ticks(migrated_url, monkeypatch, worker.webhook_tick)
    assert count == 3  # one announced, one turned into a send, one sent
    assert [b["type"] for b in receiver.bodies()] == ["call.not_connected"]
    (sent,) = deliveries(migrated_url, account_id=account)
    assert sent["status"] == "delivered"

    (again,) = run_ticks(migrated_url, monkeypatch, worker.webhook_tick)
    assert again == 0 and len(receiver.seen) == 1  # nothing is announced or sent twice


def test_the_cleanup_tick_forgets_old_events(
    api: TestClient, migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = signup(api)
    account = account_id(api, owner)
    now = datetime.now(UTC)
    for age in (45, 1):
        sql(
            migrated_url,
            "INSERT INTO webhook_events (id, account_id, type, data, created_at, fanned_out_at)"
            " VALUES (gen_random_uuid(), :a, 'lead.created', '{}', :t, :t)",
            {"a": account, "t": now - timedelta(days=age)},
        )
    (removed,) = run_ticks(migrated_url, monkeypatch, worker.webhook_prune_tick)
    assert removed == 1
    assert (
        sql(
            migrated_url,
            "SELECT count(*) FROM webhook_events WHERE account_id = :a",
            {"a": account},
        )
        == 1
    )
