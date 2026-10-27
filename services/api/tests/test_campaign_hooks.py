"""What a finished campaign call sets in motion: a callback the caller asked for, and a request not
to be called again."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.calls import postcall
from app.providers.speech import common
from app.providers.telephony.vobiz import VobizTelephony

from .campaigning import (
    NOW,
    Carrier,
    contact_rows,
    end_call,
    make_campaign,
    open_calls,
    setup_bulk,
    tick,
)
from .conftest import sql
from .helpers import run_db
from .test_post_call_job import TURNS, Gemini, model_reply

A = "+919876543210"


@pytest.fixture
def gemini(monkeypatch: pytest.MonkeyPatch) -> Iterator[Gemini]:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    fake = Gemini()
    fake.text = model_reply()
    transport = httpx.MockTransport(fake.handler)
    monkeypatch.setattr(
        common.VendorHealth,
        "client",
        lambda self, timeout=60.0: httpx.AsyncClient(transport=transport),
    )
    yield fake


def analyse(url: str) -> int:
    async def work(factory: Any) -> int:
        return await postcall.process_pending(factory, NOW + timedelta(minutes=5))

    return run_db(url, work)  # type: ignore[no-any-return]


def answered_call(
    api: TestClient,
    url: str,
    adapter: VobizTelephony,
    fake: Carrier,
    employee: str,
    owner: dict[str, str],
    **settings: Any,
) -> str:
    """A campaign call to one contact that was answered and is waiting for its analysis."""
    campaign = make_campaign(api, owner, employee, ["9876543210"], retries=2, **settings)
    tick(url, adapter, NOW)
    call = open_calls(url)[0]
    end_call(url, fake, adapter, call, NOW + timedelta(seconds=40), answered=True)
    sql(
        url,
        "UPDATE calls SET transcript = CAST(:t AS jsonb), analysis_status = 'pending'"
        " WHERE id = :c",
        {"t": json.dumps(TURNS), "c": call},
    )
    return campaign


def test_a_callback_the_contact_asked_for_is_called_at_that_time_inside_the_hours(
    api: TestClient,
    migrated_url: str,
    carrier: tuple[Carrier, VobizTelephony],
    gemini: Gemini,
) -> None:
    fake, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    answered_call(api, migrated_url, adapter, fake, employee, owner)
    assert contact_rows(migrated_url)[0][1] == "done"
    assert analyse(migrated_url) == 1
    status, attempts, when, _ = contact_rows(migrated_url)[0][1:]
    assert (status, attempts) == ("callback", 0)
    assert when == datetime(2026, 11, 3, 12, 30, tzinfo=UTC)  # 18:00 IST tomorrow
    assert sql(migrated_url, "SELECT count(*) FROM calls WHERE is_callback") == 0  # no stray call
    notes = api.get("/notifications", headers=owner).json()["items"]
    callback = [n for n in notes if n["kind"] == "callback_scheduled"]
    assert len(callback) == 1 and "03 Nov, 18:00 IST" in callback[0]["body"]
    assert tick(migrated_url, adapter, when - timedelta(minutes=1)) == []
    assert [p.outcome for p in tick(migrated_url, adapter, when)] == ["dialed"]
    assert contact_rows(migrated_url)[0][1:3] == ("calling", 1)


def test_a_callback_asked_for_at_night_waits_for_the_morning(
    api: TestClient,
    migrated_url: str,
    carrier: tuple[Carrier, VobizTelephony],
    gemini: Gemini,
) -> None:
    fake, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    gemini.text = model_reply(
        callback={
            "at": "2026-11-03T23:30:00+05:30",
            "quote": "call me tomorrow at 6 in the evening",
        }
    )
    answered_call(api, migrated_url, adapter, fake, employee, owner)
    analyse(migrated_url)
    assert contact_rows(migrated_url)[0][3] == datetime(2026, 11, 4, 3, 30, tzinfo=UTC)  # 09:00 IST


def test_a_waiting_callback_is_not_moved_by_a_second_request(
    api: TestClient,
    migrated_url: str,
    carrier: tuple[Carrier, VobizTelephony],
    gemini: Gemini,
) -> None:
    fake, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    answered_call(api, migrated_url, adapter, fake, employee, owner)
    analyse(migrated_url)
    first = contact_rows(migrated_url)[0][3]
    gemini.text = model_reply(
        callback={
            "at": "2026-11-05T12:00:00+05:30",
            "quote": "call me tomorrow at 6 in the evening",
        }
    )
    sql(migrated_url, "UPDATE calls SET analysis_status = 'pending'")
    sql(migrated_url, "UPDATE campaign_contacts SET status = 'callback'")
    analyse(migrated_url)
    assert contact_rows(migrated_url)[0][3] == first


def test_a_contact_who_asks_not_to_be_called_is_never_called_again_by_any_campaign(
    api: TestClient,
    migrated_url: str,
    carrier: tuple[Carrier, VobizTelephony],
    gemini: Gemini,
) -> None:
    fake, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    gemini.text = model_reply(
        callback=None,
        do_not_call={"requested": True, "quote": "call me tomorrow at 6 in the evening"},
    )
    answered_call(api, migrated_url, adapter, fake, employee, owner)
    analyse(migrated_url)
    assert sql(migrated_url, "SELECT source::text FROM dnc_entries") == "caller_request"
    # Another campaign, even with the do-not-call switch off, skips the person at upload.
    second = make_campaign(
        api,
        owner,
        employee,
        ["9876543210"],
        name="Second",
        skip_dnc=False,
        dedupe_days=0,
        start=False,
    )
    reason = sql(
        migrated_url, "SELECT reason FROM campaign_contacts WHERE campaign_id = :c", {"c": second}
    )
    assert reason == "asked not to be called again"
    assert api.post(f"/campaigns/{second}/start", headers=owner).status_code == 409
