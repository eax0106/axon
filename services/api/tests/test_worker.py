"""The worker is only the clock: its ticks call the tested dialer and poller functions."""

import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.providers.telephony.vobiz import BASE_URL, VobizTelephony
from worker import main as worker

from .conftest import sql
from .helpers import live_employee, seed, signup


def run_ticks(url: str, monkeypatch: pytest.MonkeyPatch, *ticks: Any) -> list[Any]:
    monkeypatch.setenv("DATABASE_URL", url)
    from app.settings import get_settings

    get_settings.cache_clear()

    async def go() -> list[Any]:
        ctx: dict[str, Any] = {}
        await worker.startup(ctx)
        try:
            return [await tick(ctx) for tick in ticks]
        finally:
            await worker.shutdown(ctx)

    return asyncio.run(go())


def test_the_cron_schedule_and_hooks() -> None:
    settings = worker.WorkerSettings
    names = {job.name: job for job in settings.cron_jobs}
    assert set(names) == {
        "cron:dial_tick",
        "cron:post_call_tick",
        "cron:reap_tick",
        "cron:sheets_tick",
    }
    assert names["cron:dial_tick"].second == set(
        range(0, 60, 3)
    )  # a lead waits seconds, not minutes
    assert settings.on_startup is worker.startup and settings.on_shutdown is worker.shutdown
    assert worker.ping in settings.functions


def test_ticks_do_nothing_and_say_so_without_carrier_keys(
    db_client: TestClient, migrated_url: str, monkeypatch: pytest.MonkeyPatch, no_keys: None
) -> None:
    seed(migrated_url)
    results = run_ticks(
        migrated_url, monkeypatch, worker.dial_tick, worker.reap_tick, worker.sheets_tick
    )
    assert results == [0, 0, 0]


def test_a_dial_tick_places_a_due_call_through_the_real_adapter(
    db_client: TestClient, migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed(migrated_url)
    owner = signup(db_client)
    employee = live_employee(db_client, migrated_url, owner)
    db_client.put(
        f"/employees/{employee}/instant/dialer",
        json={"window_start_min": 360, "window_end_min": 1320},
        headers=owner,
    )
    assert (
        db_client.post(
            f"/employees/{employee}/instant/call", json={"phone": "9876543210"}, headers=owner
        ).status_code
        == 202
    )
    sql(migrated_url, "UPDATE calls SET scheduled_for = now() - interval '1 minute'")
    monkeypatch.setenv("VOBIZ_AUTH_ID", "MA_TEST")
    monkeypatch.setenv("VOBIZ_AUTH_TOKEN", "token")
    monkeypatch.setenv("AXON_ENGINE_PUBLIC_URL", "https://engine.example.in")
    monkeypatch.setenv("AXON_API_PUBLIC_URL", "https://api.example.in")
    placed: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        placed.append(request)
        return httpx.Response(200, json={"request_uuid": "vz-9"})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        VobizTelephony,
        "_client",
        lambda self: httpx.AsyncClient(
            base_url=f"{BASE_URL}/Account/MA_TEST", headers=self._headers, transport=transport
        ),
    )
    # Freeze the worker's clock at 11:00 IST on a Monday, inside the window.
    now = datetime(2026, 11, 2, 5, 30, tzinfo=UTC)
    monkeypatch.setattr(
        worker, "datetime", type("Clock", (), {"now": staticmethod(lambda tz=None: now)})
    )
    sql(migrated_url, "UPDATE calls SET scheduled_for = '2026-11-02 05:00+00'")
    assert run_ticks(migrated_url, monkeypatch, worker.dial_tick) == [1]
    assert sql(migrated_url, "SELECT status::text || carrier_call_id FROM calls") == "ringingvz-9"
    assert len(placed) == 1
