"""The Calendar, Sheets-write and WhatsApp adapters: registered, keyed, and speaking each vendor's
documented requests. Real-vendor checks are `requires_keys` and skip until the keys exist."""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import httpx
import pytest

from app.providers.base import CalendarProvider, ProviderKind, ProviderNotConfiguredError
from app.providers.google import oauth
from app.providers.google.calendar import API, IST, GoogleCalendar
from app.providers.google.sheets import GoogleSheets
from app.providers.registry import ADAPTERS, VENDOR_KEYS, report_all, require
from app.providers.whatsapp.aisensy import AiSensyWhatsApp
from app.providers.whatsapp.interakt import InteraktWhatsApp

START = datetime(2026, 11, 3, 11, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))


def test_each_adapter_is_registered_and_needs_its_keys(
    no_keys: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = {
        (ProviderKind.CALENDAR, "google"): GoogleCalendar,
        (ProviderKind.WHATSAPP, "interakt"): InteraktWhatsApp,
        (ProviderKind.WHATSAPP, "aisensy"): AiSensyWhatsApp,
    }
    for (kind, vendor), adapter in expected.items():
        assert ADAPTERS[(kind, vendor)] is adapter and VENDOR_KEYS[kind][vendor]
    for kind in (ProviderKind.CALENDAR, ProviderKind.WHATSAPP):
        with pytest.raises(ProviderNotConfiguredError) as caught:
            require(kind)
        assert caught.value.missing_keys


def test_the_admin_report_shows_the_new_vendors_as_missing_a_key_until_it_is_set(
    no_keys: None,
) -> None:
    rows = {(r.kind, r.name): r.status for r in asyncio.run(report_all())}
    assert rows[(ProviderKind.CALENDAR, "google")] == "missing_key"
    assert rows[(ProviderKind.WHATSAPP, "interakt")] == "missing_key"
    assert rows[(ProviderKind.WHATSAPP, "aisensy")] == "missing_key"


def calendar(handler: Any, monkeypatch: pytest.MonkeyPatch) -> GoogleCalendar:
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-1")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    return GoogleCalendar(httpx.MockTransport(handler))


def test_free_busy_asks_for_india_time_and_reads_the_busy_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if str(request.url) == oauth.TOKEN_URL:
            return httpx.Response(200, json={"access_token": "at"})
        busy = [{"start": "2026-11-03T05:30:00Z", "end": "2026-11-03T06:00:00Z"}]
        return httpx.Response(200, json={"calendars": {"me@x.in": {"busy": busy}}})

    busy = asyncio.run(
        calendar(handler, monkeypatch).busy("rt", "me@x.in", START, START + timedelta(hours=1))
    )
    assert busy[0].start == datetime(2026, 11, 3, 5, 30, tzinfo=UTC)
    request = seen[-1]
    assert str(request.url) == f"{API}/freeBusy" and request.headers["authorization"] == "Bearer at"
    assert json.loads(request.content) == {
        "timeMin": "2026-11-03T11:00:00+05:30",
        "timeMax": "2026-11-03T12:00:00+05:30",
        "timeZone": "Asia/Kolkata",
        "items": [{"id": "me@x.in"}],
    }
    assert IST == "Asia/Kolkata"


def test_a_calendar_google_reports_an_error_for_is_not_read_as_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == oauth.TOKEN_URL:
            return httpx.Response(200, json={"access_token": "at"})
        return httpx.Response(200, json={"calendars": {"x": {"errors": [{"reason": "notFound"}]}}})

    with pytest.raises(RuntimeError, match="notFound"):
        asyncio.run(calendar(handler, monkeypatch).busy("rt", "x", START, START))


def test_an_event_has_the_callers_id_and_no_guests_and_a_repeat_is_reported_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[httpx.Request] = []
    status = [200, 409]

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == oauth.TOKEN_URL:
            return httpx.Response(200, json={"access_token": "at"})
        seen.append(request)
        return httpx.Response(status.pop(0), json={})

    adapter: CalendarProvider = calendar(handler, monkeypatch)
    end = START + timedelta(minutes=30)

    def make() -> Any:
        return asyncio.run(
            adapter.create_event("rt", "primary", "abc123", "Visit", "Name: A", START, end)
        )

    assert make() is True
    assert make() is False  # Google's 409: the same id is already there
    body = json.loads(seen[0].content)
    assert body["id"] == "abc123" and "attendees" not in body
    assert body["start"] == {"dateTime": "2026-11-03T11:00:00+05:30", "timeZone": "Asia/Kolkata"}
    assert str(seen[0].url) == f"{API}/calendars/primary/events"


def test_deleting_an_event_that_is_gone_is_fine_and_other_errors_are_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    status = [204, 404, 410, 500]

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == oauth.TOKEN_URL:
            return httpx.Response(200, json={"access_token": "at"})
        assert request.method == "DELETE"
        return httpx.Response(status.pop(0))

    adapter = calendar(handler, monkeypatch)
    for _ in range(3):
        asyncio.run(adapter.delete_event("rt", "primary", "abc"))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(adapter.delete_event("rt", "primary", "abc"))


def test_revoking_a_token_already_revoked_is_fine(monkeypatch: pytest.MonkeyPatch) -> None:
    status = [200, 400, 500]

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == oauth.REVOKE_URL
        return httpx.Response(status.pop(0))

    adapter = calendar(handler, monkeypatch)
    asyncio.run(adapter.revoke("rt"))
    asyncio.run(adapter.revoke("rt"))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(adapter.revoke("rt"))


def test_a_sheet_row_is_appended_as_raw_text_under_the_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "c")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "s")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == oauth.TOKEN_URL:
            return httpx.Response(200, json={"access_token": "at"})
        seen.append(request)
        return httpx.Response(200, json={})

    asyncio.run(
        GoogleSheets(httpx.MockTransport(handler)).append_row(
            "rt", "sheet 1", "Leads!A:C", ["a", "=1+1"]
        )
    )
    [request] = seen
    assert (
        str(request.url)
        .split("?")[0]
        .endswith("/spreadsheets/sheet%201/values/Leads%21A%3AC:append")
    )
    assert dict(request.url.params) == {
        "valueInputOption": "RAW",
        "insertDataOption": "INSERT_ROWS",
    }
    assert json.loads(request.content) == {"values": [["a", "=1+1"]]}


@pytest.mark.requires_keys("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET")
def test_google_accepts_our_oauth_client_for_calendar() -> None:
    asyncio.run(GoogleCalendar().health())


@pytest.mark.requires_keys(
    "GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
    "GOOGLE_TEST_REFRESH_TOKEN",
    "GOOGLE_TEST_CALENDAR_ID",
)
def test_google_books_and_removes_an_event_on_a_real_calendar() -> None:
    token, calendar_id = (
        os.environ["GOOGLE_TEST_REFRESH_TOKEN"],
        os.environ["GOOGLE_TEST_CALENDAR_ID"],
    )
    start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) + timedelta(days=30)

    async def go() -> None:
        adapter = GoogleCalendar()
        await adapter.busy(token, calendar_id, start, start + timedelta(hours=1))
        assert await adapter.create_event(
            token, calendar_id, "axoncontract01", "Axon contract test", "removed at once", start,
            start + timedelta(minutes=10),
        )  # fmt: skip
        await adapter.delete_event(token, calendar_id, "axoncontract01")

    asyncio.run(go())


@pytest.mark.requires_keys(
    "GOOGLE_OAUTH_CLIENT_ID",
    "GOOGLE_OAUTH_CLIENT_SECRET",
    "GOOGLE_TEST_REFRESH_TOKEN",
    "GOOGLE_TEST_SHEET_ID",
)
def test_google_appends_a_row_to_a_real_sheet() -> None:
    asyncio.run(
        GoogleSheets().append_row(
            os.environ["GOOGLE_TEST_REFRESH_TOKEN"],
            os.environ["GOOGLE_TEST_SHEET_ID"],
            "A:Z",
            ["axon contract test"],
        )
    )


@pytest.mark.requires_keys("INTERAKT_API_KEY", "WHATSAPP_TEST_PHONE", "INTERAKT_TEST_TEMPLATE")
def test_interakt_sends_a_template_to_the_test_phone() -> None:
    asyncio.run(
        InteraktWhatsApp().send_template(
            os.environ["WHATSAPP_TEST_PHONE"],
            os.environ["INTERAKT_TEST_TEMPLATE"],
            "en",
            [],
            "Test",
        )
    )


@pytest.mark.requires_keys("AISENSY_API_KEY", "WHATSAPP_TEST_PHONE", "AISENSY_TEST_CAMPAIGN")
def test_aisensy_sends_a_campaign_to_the_test_phone() -> None:
    asyncio.run(
        AiSensyWhatsApp().send_template(
            os.environ["WHATSAPP_TEST_PHONE"], os.environ["AISENSY_TEST_CAMPAIGN"], "en", [], "Test"
        )
    )
