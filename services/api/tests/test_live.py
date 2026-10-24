import json
import os
import threading
import time
from typing import Any

import pytest
import redis
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.live import channel

from .conftest import sql
from .test_auth import _signup


@pytest.fixture
def redis_url(monkeypatch: pytest.MonkeyPatch) -> str:
    url = os.environ.get("AXON_TEST_REDIS_URL")
    if not url:
        pytest.skip("AXON_TEST_REDIS_URL not set; live event tests need a real Redis")
    monkeypatch.setenv("REDIS_URL", url)
    return url


def _call(migrated_url: str) -> str:
    account = sql(migrated_url, "SELECT account_id FROM users LIMIT 1")
    query = (
        "INSERT INTO calls (account_id, direction, channel, status) "
        "VALUES (:a, 'outbound', 'instant', 'in_progress') RETURNING id::text"
    )
    call_id: str = sql(migrated_url, query, {"a": account})
    return call_id


def _subscribers(client: redis.Redis, call_id: str) -> int:
    counts: list[tuple[bytes, int]] = client.pubsub_numsub(channel(call_id))  # type: ignore[assignment]
    return counts[0][1]


def _publish_until_heard(url: str, call_id: str, events: list[dict[str, Any]]) -> None:
    """Act as the engine: wait for the API to subscribe, then publish the events."""
    client = redis.Redis.from_url(url)
    deadline = time.monotonic() + 5
    while not _subscribers(client, call_id) and time.monotonic() < deadline:
        time.sleep(0.02)
    for event in events:
        client.publish(channel(call_id), json.dumps(event))
    client.close()


def test_live_events_reach_the_calls_owner_until_the_call_ends(
    redis_url: str, db_client: TestClient, migrated_url: str
) -> None:
    token = _signup(db_client)
    call_id = _call(migrated_url)
    events = [
        {"type": "started", "call_id": call_id},
        {"type": "user_transcript", "text": "నమస్కారం"},
        {"type": "ended", "reason": "silence"},
    ]
    publisher = threading.Thread(target=_publish_until_heard, args=(redis_url, call_id, events))
    received: list[dict[str, Any]] = []
    with db_client.websocket_connect(f"/calls/{call_id}/live?token={token}") as ws:
        publisher.start()
        try:
            while True:
                received.append(json.loads(ws.receive_text()))
        except WebSocketDisconnect:
            pass
    publisher.join()
    assert received == events


@pytest.mark.parametrize("bad", ["", "garbage"])
def test_live_events_refuse_a_bad_token(
    redis_url: str, db_client: TestClient, migrated_url: str, bad: str
) -> None:
    _signup(db_client)
    call_id = _call(migrated_url)
    # The handshake completes (a pre-accept close would be an HTTP 403 without the code).
    with db_client.websocket_connect(f"/calls/{call_id}/live?token={bad}") as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert closed.value.code == 4401


def test_live_events_refuse_another_accounts_call(
    redis_url: str, db_client: TestClient, migrated_url: str
) -> None:
    _signup(db_client)
    call_id = _call(migrated_url)
    other = _signup(db_client, email="someone@else.in")
    with db_client.websocket_connect(f"/calls/{call_id}/live?token={other}") as ws:
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert closed.value.code == 4404
