import asyncio
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient

from app.instant import sheets as poller
from app.providers.base import ProviderKind
from app.providers.google.sheets import SCOPE, TOKEN_URL, GoogleSheets, consent_url
from app.providers.registry import ADAPTERS, require

from .conftest import sql
from .helpers import live_employee, run_db, seed, signup

NOW = datetime(2026, 11, 2, 5, 30, tzinfo=UTC)
HEADER = ["Name", "Phone", "Budget"]


class Google:
    def __init__(self) -> None:
        self.rows: list[list[str]] = [HEADER, ["Old Lead", "9000000001", "1"]]
        self.requests: list[httpx.Request] = []
        self.token_error: str | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if str(request.url) == TOKEN_URL:
            form = parse_qs(request.content.decode())
            if self.token_error:
                return httpx.Response(400, json={"error": self.token_error})
            if form["grant_type"] == ["authorization_code"]:
                return httpx.Response(
                    200, json={"access_token": "at", "refresh_token": "rt-1", "expires_in": 3599}
                )
            if form["refresh_token"] == ["probe"]:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "at-fresh", "expires_in": 3599})
        assert request.headers["authorization"] == "Bearer at-fresh"
        return httpx.Response(
            200, json={"range": "Sheet1!A1:C", "majorDimension": "ROWS", "values": self.rows}
        )


@pytest.fixture
def api(
    db_client: TestClient, migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, Google]]:
    seed(migrated_url)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-1")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")
    google = Google()
    transport = httpx.MockTransport(google.handler)
    monkeypatch.setattr(
        GoogleSheets, "_client", lambda self: httpx.AsyncClient(transport=transport)
    )
    yield db_client, google


def connected(client: TestClient, url: str) -> tuple[str, dict[str, str]]:
    owner = signup(client)
    employee = live_employee(client, url, owner, variables=("budget",))
    base = f"/employees/{employee}/instant/sheets"
    assert (
        client.post(
            base + "/connect",
            json={"code": "auth-code", "redirect_uri": "https://app.example.in/cb"},
            headers=owner,
        ).status_code
        == 200
    )
    assert (
        client.put(
            base, json={"sheet_id": "sheet-1", "range": "Sheet1!A:C"}, headers=owner
        ).status_code
        == 200
    )
    return employee, owner


def poll(url: str, now: datetime = NOW) -> int:
    async def work(factory: Any) -> int:
        return await poller.poll_all(factory, require(ProviderKind.SHEETS), now)  # type: ignore[arg-type]

    return run_db(url, work)  # type: ignore[no-any-return]


def test_the_consent_url_asks_for_read_only_offline_access(api: tuple[TestClient, Google]) -> None:
    client, _ = api
    owner = signup(client)
    employee = client.post("/employees", json={"channel": "instant"}, headers=owner).json()["id"]
    url = client.get(
        f"/employees/{employee}/instant/sheets/consent-url",
        params={"redirect_uri": "https://app.example.in/cb"},
        headers=owner,
    ).json()["url"]
    query = parse_qs(url.split("?", 1)[1])
    assert (
        query["scope"] == [SCOPE]
        and query["access_type"] == ["offline"]
        and query["client_id"] == ["client-1"]
    )
    assert query["state"] == [employee] and url == consent_url(
        "https://app.example.in/cb", employee
    )


def test_connecting_exchanges_the_code_and_stores_the_refresh_token(
    api: tuple[TestClient, Google], migrated_url: str
) -> None:
    client, google = api
    connected(client, migrated_url)
    exchange = next(
        r
        for r in google.requests
        if parse_qs(r.content.decode()).get("grant_type") == ["authorization_code"]
    )
    form = parse_qs(exchange.content.decode())
    assert form["code"] == ["auth-code"] and form["client_secret"] == ["client-secret"]
    assert form["redirect_uri"] == ["https://app.example.in/cb"]
    assert sql(migrated_url, "SELECT google_refresh_token FROM lead_connections") == "rt-1"


def test_existing_rows_are_skipped_at_connect_and_new_rows_become_leads(
    api: tuple[TestClient, Google], migrated_url: str
) -> None:
    client, google = api
    employee, owner = connected(client, migrated_url)
    assert (
        sql(migrated_url, "SELECT sheet_cursor FROM lead_connections") == 2
    )  # header + the old lead
    assert poll(migrated_url) == 0 and sql(migrated_url, "SELECT count(*) FROM calls") == 0
    google.rows += [["Ravi", "98765 43210", "5 lakh"], ["Sita", "9876543211", "2 lakh"]]
    assert poll(migrated_url) == 2
    assert sql(migrated_url, "SELECT count(*) FROM calls WHERE status = 'queued'") == 2
    assert (
        sql(migrated_url, "SELECT name || fields::text FROM leads WHERE phone = '+919876543210'")
        == 'Ravi{"budget": "5 lakh"}'
    )
    assert sql(migrated_url, "SELECT sheet_cursor FROM lead_connections") == 4
    assert poll(migrated_url) == 0  # nothing new: the cursor held
    log = client.get(f"/employees/{employee}/instant/intake-log", headers=owner).json()
    assert {e["source"] for e in log} == {"sheets"} and len(log) == 2


def test_a_bad_row_is_logged_rejected_and_the_cursor_still_moves(
    api: tuple[TestClient, Google], migrated_url: str
) -> None:
    client, google = api
    employee, owner = connected(client, migrated_url)
    google.rows += [["No Phone", "", "1"], ["Ok", "9876543212", "3"]]
    assert poll(migrated_url) == 2
    log = client.get(f"/employees/{employee}/instant/intake-log", headers=owner).json()
    assert sorted(e["status"] for e in log) == ["accepted", "rejected"]
    assert sql(migrated_url, "SELECT sheet_cursor FROM lead_connections") == 4


def test_short_rows_and_a_header_only_sheet_are_fine(
    api: tuple[TestClient, Google], migrated_url: str
) -> None:
    client, google = api
    connected(client, migrated_url)
    google.rows += [["Short", "9876543213"]]  # Google trims trailing empty cells
    assert poll(migrated_url) == 1
    google.rows = [HEADER]
    assert poll(migrated_url) == 0


def test_the_values_request_is_pinned(api: tuple[TestClient, Google], migrated_url: str) -> None:
    client, google = api
    connected(client, migrated_url)
    request = google.requests[-1]
    assert request.method == "GET"
    assert (
        str(request.url)
        == "https://sheets.googleapis.com/v4/spreadsheets/sheet-1/values/Sheet1%21A%3AC"
    )
    refresh = [
        r
        for r in google.requests
        if parse_qs(r.content.decode()).get("grant_type") == ["refresh_token"]
    ][-1]
    assert parse_qs(refresh.content.decode())["refresh_token"] == ["rt-1"]


def test_choosing_a_sheet_needs_google_connected_first(api: tuple[TestClient, Google]) -> None:
    client, _ = api
    owner = signup(client)
    employee = client.post("/employees", json={"channel": "instant"}, headers=owner).json()["id"]
    response = client.put(
        f"/employees/{employee}/instant/sheets", json={"sheet_id": "s"}, headers=owner
    )
    assert response.status_code == 409


def test_health_accepts_invalid_grant_and_rejects_a_bad_client(
    api: tuple[TestClient, Google],
) -> None:
    _, google = api
    asyncio.run(GoogleSheets().health())
    assert parse_qs(google.requests[-1].content.decode())["refresh_token"] == ["probe"]
    google.token_error = "invalid_client"  # noqa: S105 - an OAuth error code
    with pytest.raises(RuntimeError, match="invalid_client"):
        asyncio.run(GoogleSheets().health())
    assert ADAPTERS[(ProviderKind.SHEETS, "google")] is GoogleSheets


def test_without_google_keys_the_sheets_endpoints_are_503(
    db_client: TestClient, migrated_url: str, no_keys: None
) -> None:
    seed(migrated_url)
    owner = signup(db_client)
    employee = db_client.post("/employees", json={"channel": "instant"}, headers=owner).json()["id"]
    response = db_client.get(
        f"/employees/{employee}/instant/sheets/consent-url",
        params={"redirect_uri": "https://x.example/cb"},
        headers=owner,
    )
    assert response.status_code == 503 and response.json()["kind"] == "sheets"
    assert json.dumps(response.json())
