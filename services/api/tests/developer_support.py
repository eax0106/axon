"""Shared by the developer-platform tests: API keys, a webhook receiver, and the worker's webhook
tick run by hand on simulated time."""

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler
from typing import Any, ClassVar

from fastapi.testclient import TestClient

from app.developer import delivery, settle

from .helpers import run_db

NOW = datetime(2026, 11, 2, 5, 30, tzinfo=UTC)


class Receiver(BaseHTTPRequestHandler):
    """Records what it is sent. `answers` are the status codes it gives, one per request, then
    200; a path starting /redirect answers 302."""

    base: ClassVar[str] = ""
    seen: ClassVar[list[dict[str, Any]]] = []
    answers: ClassVar[list[int]] = []

    @classmethod
    def reset(cls) -> None:
        cls.seen, cls.answers = [], []

    def log_message(self, *_: Any) -> None:
        return None

    def do_POST(self) -> None:
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length)
        Receiver.seen.append({"path": self.path, "headers": dict(self.headers), "body": body})
        code = Receiver.answers.pop(0) if Receiver.answers else 200
        if self.path.startswith("/redirect"):
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/inside")
        else:
            self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    @classmethod
    def bodies(cls) -> list[dict[str, Any]]:
        return [json.loads(r["body"]) for r in cls.seen]


def verify(secret: str, header: str, body: bytes) -> bool:
    """The receiver's side of the documented scheme, written out independently of the server."""
    parts = dict(p.split("=", 1) for p in header.split(","))
    expected = hmac.new(secret.encode(), f"{parts['t']}.".encode() + body, hashlib.sha256)
    return hmac.compare_digest(expected.hexdigest(), parts["v1"])


def make_key(api: TestClient, owner: dict[str, str], name: str = "n8n") -> str:
    response = api.post("/developer/keys", json={"name": name}, headers=owner)
    assert response.status_code == 201, response.text
    return str(response.json()["key"])


def bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def make_webhook(
    api: TestClient, owner: dict[str, str], url: str, events: list[str] | None = None
) -> dict[str, Any]:
    body = {"url": url, "events": events or ["call.completed"]}
    response = api.post("/developer/webhooks", json=body, headers=owner)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def tick(url: str, now: datetime = NOW) -> int:
    """What the worker does every few seconds for the webhooks."""

    async def work(factory: Any) -> int:
        n = await settle.settle_calls(factory, now)
        n += await delivery.fan_out(factory, now)
        return n + await delivery.deliver_due(factory, now)

    result: int = run_db(url, work)
    return result


def rows(url: str, query: str, **params: Any) -> list[dict[str, Any]]:
    """Every row of a read-only query as a dict."""
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def go() -> list[dict[str, Any]]:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                found = await conn.execute(text(query), params)
                return [dict(r) for r in found.mappings()]
        finally:
            await engine.dispose()

    return asyncio.run(go())


def deliveries(url: str, **where: Any) -> list[dict[str, Any]]:
    """The delivery rows, oldest first."""
    clause = " AND ".join(f"{k} = :{k}" for k in where) or "true"
    query = f"SELECT * FROM webhook_deliveries WHERE {clause} ORDER BY created_at"  # noqa: S608
    return rows(url, query, **where)


def events_of(url: str, type_: str | None = None) -> list[dict[str, Any]]:
    """The events written so far, oldest first, with `data` as a dict."""
    found = rows(url, "SELECT * FROM webhook_events ORDER BY created_at, id")
    return [e for e in found if type_ is None or e["type"] == type_]


def announce(
    url: str,
    account: Any,
    type_: str = "call.completed",
    data: dict[str, Any] | None = None,
    employee: Any = None,
) -> uuid.UUID:
    """Write an event the way the app does, as if something had just happened."""
    from app.developer import events

    async def work(factory: Any) -> uuid.UUID:
        async with factory() as session:
            event = events.record(session, account, type_, data or events.sample(type_), employee)
            await session.commit()
            return event.id

    found: uuid.UUID = run_db(url, work)
    return found
