"""Shared pieces for the in-call action tests: Google behind a fake HTTP transport, a connected
account, and an employee with actions."""

import json
import time
import uuid
from http.server import BaseHTTPRequestHandler
from typing import Any, ClassVar
from urllib.parse import parse_qs

import httpx
from fastapi.testclient import TestClient

from app.providers.google import calendar as g_calendar
from app.providers.google import oauth
from app.providers.google import sheets as g_sheets

REDIRECT = "https://app.example.in/cb"
ALL_SCOPES = " ".join([*g_calendar.SCOPES, g_sheets.WRITE_SCOPE])


class Google:
    """Just enough of Google's token, Calendar and Sheets endpoints to see what we send."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.granted = ALL_SCOPES
        self.busy: list[tuple[str, str]] = []  # ISO start and end
        self.events: dict[str, dict[str, Any]] = {}
        self.deleted: list[str] = []
        self.rows: list[list[str]] = [["Name", "Plan"], ["Asha", "Gold"], ["Ravi", "Silver"]]
        self.appended: list[dict[str, Any]] = []
        self.revoked: list[str] = []
        self.calendar_error: str | None = None
        self.sheets_status = 200

    def handler(self, request: httpx.Request) -> Any:
        self.requests.append(request)
        url = str(request.url).split("?")[0]
        if url == oauth.TOKEN_URL:
            form = parse_qs(request.content.decode())
            if form["grant_type"] == ["authorization_code"]:
                body = {"access_token": "at", "refresh_token": "rt-1", "scope": self.granted}
                return httpx.Response(200, json=body)
            return httpx.Response(200, json={"access_token": "at-fresh"})
        if url == oauth.REVOKE_URL:
            self.revoked.append(parse_qs(request.content.decode())["token"][0])
            return httpx.Response(200)
        assert request.headers["authorization"] == "Bearer at-fresh"
        if url.endswith("/freeBusy"):
            asked = json.loads(request.content)["items"][0]["id"]
            taken = [(e["start"]["dateTime"], e["end"]["dateTime"]) for e in self.events.values()]
            entry: dict[str, Any] = {"busy": [{"start": s, "end": e} for s, e in self.busy + taken]}
            if self.calendar_error:
                entry = {"errors": [{"reason": self.calendar_error}]}
            return httpx.Response(200, json={"calendars": {asked: entry}})
        if "/events" in url:
            if request.method == "DELETE":
                event = url.rsplit("/", 1)[1]
                if event not in self.events:
                    return httpx.Response(404, json={})
                self.deleted.append(event)
                del self.events[event]
                return httpx.Response(204)
            body = json.loads(request.content)
            if body["id"] in self.events:
                return httpx.Response(409, json={"error": "duplicate"})
            self.events[body["id"]] = body
            return httpx.Response(200, json=body)
        if url.endswith(":append"):
            assert request.url.params["valueInputOption"] == "RAW"
            self.appended.append(json.loads(request.content))
            return httpx.Response(200, json={})
        if self.sheets_status != 200:
            return httpx.Response(self.sheets_status, json={})
        return httpx.Response(200, json={"values": self.rows})


def patch_google(monkeypatch: Any) -> Google:
    """Point every Google adapter at one fake account."""
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-1")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")
    google = Google()
    transport = httpx.MockTransport(google.handler)
    for adapter in (g_sheets.GoogleSheets, g_calendar.GoogleCalendar):
        monkeypatch.setattr(adapter, "_client", lambda self: httpx.AsyncClient(transport=transport))
    return google


def connect_google(
    client: TestClient, owner: dict[str, str], services: tuple[str, ...] = ("calendar", "sheets")
) -> dict[str, Any]:
    url = client.get(
        "/integrations/google/consent-url",
        params={"redirect_uri": REDIRECT, "services": list(services)},
        headers=owner,
    ).json()["url"]
    state = parse_qs(url.split("?", 1)[1])["state"][0]
    body = {"code": "auth-code", "redirect_uri": REDIRECT, "state": state}
    response = client.post("/integrations/google/connect", json=body, headers=owner)
    assert response.status_code == 200, response.text
    return dict(response.json())


def put_actions(
    client: TestClient, owner: dict[str, str], employee: str, *actions: dict[str, Any]
) -> Any:
    return client.put(
        f"/employees/{employee}/actions", json={"actions": list(actions)}, headers=owner
    )


def sheet_write(**changes: Any) -> dict[str, Any]:
    return {
        "kind": "sheet_write",
        "name": "save_lead",
        "description": "Save the caller's details.",
        "sheet_id": "sheet-1",
        "columns": [{"name": "name", "description": "Caller name"}],
        **changes,
    }


def calendar_action(**changes: Any) -> dict[str, Any]:
    return {"kind": "calendar_booking", "name": "visit", "description": "Book a visit.", **changes}


def http_action(**changes: Any) -> dict[str, Any]:
    return {
        "kind": "http_api",
        "name": "order_status",
        "description": "Look up an order.",
        "url": "https://shop.example.in/orders/{order_id}",
        "params": [{"name": "order_id", "description": "The order number"}],
        **changes,
    }


def use(
    url: str,
    client: TestClient,
    owner: dict[str, str],
    actions: list[dict[str, Any]],
    calls: list[tuple[str, dict[str, Any]]],
    **context: Any,
) -> list[dict[str, Any]]:
    """Build the tools for `actions` as a call would and run `calls` in order; the results."""
    from app.actions.tools import ActionContext, build_tools
    from app.employees.script import ScriptBundle

    from .helpers import account_id, run_db

    account = uuid.UUID(account_id(client, owner))
    parsed = ScriptBundle.model_validate({"actions": actions}).actions

    async def work(factory: Any) -> list[dict[str, Any]]:
        tools = {t.name: t for t in build_tools(parsed, ActionContext(factory, account, **context))}
        return [await tools[name].run(args) for name, args in calls]

    return run_db(url, work)  # type: ignore[no-any-return]


PHONE = "+919876543210"
WHATSAPP_ACTION = {
    "kind": "whatsapp",
    "name": "send_price",
    "description": "Send the price list.",
    "template": "price_list",
    "language": "hi",
    "params": [
        {"name": "plan", "description": "The plan they asked about"},
        {"name": "city", "description": "Their city", "required": False},
    ],
}


class Shop(BaseHTTPRequestHandler):
    seen: ClassVar[list[dict[str, Any]]] = []

    def log_message(self, *_: Any) -> None:
        return None

    def _answer(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length).decode() if length else ""
        Shop.seen.append(
            {"method": self.command, "path": self.path, "headers": dict(self.headers), "body": body}
        )
        if self.path.startswith("/redirect"):
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/inside")
            self.end_headers()
            return
        if self.path.startswith("/slow"):
            time.sleep(3)
        data = (
            b"x" * 200_000
            if self.path.startswith("/big")
            else json.dumps({"path": self.path, "body": body}).encode()
        )
        code = 500 if self.path.startswith("/boom") else 200
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        try:
            self.wfile.write(data)
        except BrokenPipeError:
            pass

    do_GET = do_POST = do_PUT = do_DELETE = _answer


class Vendor:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.status = 200
        self.body: dict[str, Any] = {"result": True, "message": "Message created successfully"}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json=self.body)

    def sent(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests]
