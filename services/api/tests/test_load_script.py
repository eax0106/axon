import asyncio
import importlib.util
import os
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import redis
import uvicorn

from app import ratelimit
from app.db import Base
from app.main import app
from app.settings import get_settings

from .conftest import TEST_JWT_SECRET, reseed_dial_rules, sql

SCRIPT = Path(__file__).parents[3] / "scripts" / "load_test.py"
spec = importlib.util.spec_from_file_location("load_test_script", SCRIPT)
assert spec and spec.loader
load_test = importlib.util.module_from_spec(spec)
spec.loader.exec_module(load_test)


@pytest.fixture
def server(migrated_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """The API on a real port, as the script meets it, with a real database behind it."""
    monkeypatch.setenv("DATABASE_URL", migrated_url)
    monkeypatch.setenv("AXON_JWT_SECRET", TEST_JWT_SECRET)
    get_settings.cache_clear()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    running = uvicorn.Server(config)
    thread = threading.Thread(target=running.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not running.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert running.started, "the test server did not start"
    yield f"http://127.0.0.1:{port}"
    running.should_exit = True
    thread.join(10)
    get_settings.cache_clear()
    tables = ", ".join(f'"{t}"' for t in Base.metadata.tables)
    sql(migrated_url, f"TRUNCATE {tables} CASCADE")
    reseed_dial_rules(migrated_url)


def test_every_user_signs_up_signs_in_and_reads_every_route_without_an_error(server: str) -> None:
    users, rounds = 8, 3
    report = load_test.run(server, users, rounds)
    result = asyncio.run(report)
    assert result.errors == []
    assert result.ok
    for route in load_test.READS:
        assert len(result.latencies[route]) == users * rounds
    assert len(result.latencies["/auth/signup"]) == users
    assert len(result.latencies["/auth/login"]) == users
    assert "LOAD TEST PASSED" in result.render()
    assert "p95 ms" in result.render()


def test_a_p95_above_the_limit_fails_the_run(server: str) -> None:
    result = asyncio.run(load_test.run(server, 3, 2, max_p95_ms=0.001))
    assert not result.ok
    assert result.errors == []
    assert set(result.slow()) == set(load_test.READS)
    assert "LOAD TEST FAILED" in result.render()


def test_a_server_that_cannot_be_reached_fails_the_run() -> None:
    result = asyncio.run(load_test.run("http://127.0.0.1:1", 2, 1))
    assert not result.ok
    assert len(result.errors) == 2


@pytest.fixture
def counting_redis(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The sign-up limit on (2 an hour), counted in a real Redis; ask for it before `server`."""
    url = os.environ.get("AXON_TEST_REDIS_URL")
    if not url:
        pytest.skip("AXON_TEST_REDIS_URL not set; rate limit tests need a real Redis")
    monkeypatch.setenv("REDIS_URL", url)
    monkeypatch.delenv(ratelimit.OFF_ENV)
    monkeypatch.setattr(ratelimit, "SIGNUPS_PER_HOUR", 2)
    with redis.Redis.from_url(url) as client:
        client.flushdb()
        yield
        client.flushdb()


def test_the_sign_up_rate_limit_is_named_as_the_reason(counting_redis: None, server: str) -> None:
    result = asyncio.run(load_test.run(server, 4, 1))
    assert result.refused_by_rate_limit
    assert not result.ok
    assert "AXON_AUTH_RATE_LIMIT=off" in result.render()
