"""Shared by the incoming-call tests: an inbound employee on a number, and a call arriving on it."""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.inbound import routing
from app.providers.telephony.vobiz import BASE_URL, VobizTelephony

from .conftest import sql
from .dialing import Carrier
from .helpers import live_employee, run_db, signup

NOW = datetime(2026, 11, 2, 5, 30, tzinfo=UTC)  # 11:00 IST on a Monday
NUMBER = "+919100000001"
CALLER = "+919876543210"


@pytest.fixture
def routed_carrier(monkeypatch: pytest.MonkeyPatch) -> Iterator[Carrier]:
    """The carrier the API itself talks to: every adapter the registry builds goes through it."""
    monkeypatch.setenv("VOBIZ_AUTH_ID", "MA_TEST")
    monkeypatch.setenv("VOBIZ_AUTH_TOKEN", "token")
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")  # the speech legs: no call starts without them
    fake = Carrier()
    transport = httpx.MockTransport(fake.handler)
    monkeypatch.setattr(
        VobizTelephony,
        "_client",
        lambda self: httpx.AsyncClient(
            base_url=f"{BASE_URL}/Account/MA_TEST", headers=self._headers, transport=transport
        ),
    )
    yield fake


def adapter(fake: Carrier) -> VobizTelephony:
    return VobizTelephony(transport=httpx.MockTransport(fake.handler))


def inbound_employee(
    api: TestClient,
    url: str,
    *,
    channel: str = "inbound",
    number: str = NUMBER,
    settings: dict[str, Any] | None = None,
    live: bool = True,
) -> tuple[str, dict[str, str]]:
    """A live employee on `number`; `settings` are its inbound settings."""
    owner = signup(api)
    employee = live_employee(api, url, owner, channel=channel, number=number, live=False)
    if settings is not None:
        put = api.put(f"/employees/{employee}/inbound-settings", json=settings, headers=owner)
        assert put.status_code == 200, put.text
    if live:
        sql(url, "UPDATE employees SET status = 'live' WHERE id = :e", {"e": employee})
    return employee, owner


def ring(
    url: str,
    fake: Carrier,
    *,
    to: str = NUMBER,
    caller: str = CALLER,
    carrier_id: str | None = None,
    now: datetime = NOW,
    live: bool = True,
) -> routing.Routed:
    """A call from `caller` arrives on `to`. The carrier has it live unless `live` is False."""
    carrier_id = carrier_id or f"leg-{uuid.uuid4().hex[:8]}"
    if live:
        fake.live.add(carrier_id)
        fake.parties[carrier_id] = (caller, to)

    async def work(factory: Any) -> routing.Routed:
        return await routing.route(factory, adapter(fake), carrier_id=carrier_id, now=now)

    out: routing.Routed = run_db(url, work)
    return out


def calls(url: str, where: str = "true") -> list[dict[str, Any]]:
    async def work(factory: Any) -> list[dict[str, Any]]:
        from sqlalchemy import text

        async with factory() as session:
            rows = await session.execute(
                text(f"SELECT * FROM calls WHERE {where} ORDER BY created_at")  # noqa: S608
            )
            return [dict(r._mapping) for r in rows]

    out: list[dict[str, Any]] = run_db(url, work)
    return out


def events(url: str, call_id: Any) -> list[tuple[str, dict[str, Any]]]:
    async def work(factory: Any) -> list[tuple[str, dict[str, Any]]]:
        from sqlalchemy import text

        async with factory() as session:
            rows = await session.execute(
                text("SELECT type, data FROM call_events WHERE call_id = :c ORDER BY id"),
                {"c": call_id},
            )
            return [(r[0], r[1]) for r in rows]

    out: list[tuple[str, dict[str, Any]]] = run_db(url, work)
    return out
