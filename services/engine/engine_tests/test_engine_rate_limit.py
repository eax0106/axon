"""The engine's public Vobiz URLs are limited per address (security test 26 Nov, L4)."""

import os
from collections.abc import Iterator

import pytest
import redis
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import engine.main
from app import ratelimit
from app.settings import get_settings
from engine.main import app

from .test_call import providers  # noqa: F401 - fixture


@pytest.fixture
def limited(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Limits on (the suite turns them off), a limit of 2, counted in a Redis that starts empty."""
    url = os.environ.get("AXON_TEST_REDIS_URL")
    if not url:
        pytest.skip("AXON_TEST_REDIS_URL not set; rate limit tests need a real Redis")
    monkeypatch.setenv("REDIS_URL", url)
    monkeypatch.delenv(ratelimit.OFF_ENV)
    monkeypatch.setattr(engine.main, "PER_ADDRESS_PER_MINUTE", 2)
    get_settings.cache_clear()
    with redis.Redis.from_url(url) as client:
        client.flushdb()
        yield
        client.flushdb()
    get_settings.cache_clear()


@pytest.mark.parametrize("path", ["/vobiz/answer", "/vobiz/inbound"])
def test_the_answer_urls_turn_an_address_away_past_the_limit(
    providers: None,  # noqa: F811
    limited: None,
    path: str,
) -> None:
    with TestClient(app) as client:
        codes = [client.post(path).status_code for _ in range(3)]
    assert codes == [401, 401, 429]  # unsigned, so refused, and then not even looked at


def test_the_stream_turns_an_address_away_before_reading_anything(
    providers: None,  # noqa: F811
    limited: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine.main, "START_TIMEOUT_S", 0.2)
    reasons = []
    with TestClient(app) as client:
        for _ in range(3):
            with client.websocket_connect("/vobiz/stream") as ws:
                with pytest.raises(WebSocketDisconnect) as closed:
                    ws.receive_text()
            reasons.append((closed.value.code, closed.value.reason))
    assert reasons == [
        (1008, "no valid start message"),
        (1008, "no valid start message"),
        (1008, "too many requests"),
    ]
