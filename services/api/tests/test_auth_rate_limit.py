import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest
import redis
from fastapi.testclient import TestClient

from app import ratelimit

from .test_auth import EMAIL, PASSWORD, _auth, _signup

WRONG = "wrong password"


@pytest.fixture
def limited(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """The limits switched on, counted in a real Redis that starts empty."""
    url = os.environ.get("AXON_TEST_REDIS_URL")
    if not url:
        pytest.skip("AXON_TEST_REDIS_URL not set; rate limit tests need a real Redis")
    monkeypatch.setenv("REDIS_URL", url)
    monkeypatch.delenv(ratelimit.OFF_ENV)
    with redis.Redis.from_url(url) as client:
        client.flushdb()
        yield url
        client.flushdb()


def _login(client: TestClient, email: str = EMAIL, password: str = PASSWORD) -> int:
    return client.post("/auth/login", json={"email": email, "password": password}).status_code


def test_the_eleventh_wrong_password_for_an_email_is_refused_even_if_it_is_right(
    limited: str, db_client: TestClient
) -> None:
    _signup(db_client)
    assert [_login(db_client, password=WRONG) for _ in range(10)] == [401] * 10
    locked = db_client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert locked.status_code == 429
    assert 1 <= int(locked.headers["Retry-After"]) <= ratelimit.WINDOW_S


def test_an_unknown_email_is_limited_the_same_way_and_others_are_not(
    limited: str, db_client: TestClient
) -> None:
    _signup(db_client)
    assert [_login(db_client, "no@one.in") for _ in range(10)] == [401] * 10
    assert _login(db_client, "no@one.in") == 429
    assert _login(db_client) == 200  # a different email from the same address still signs in


def test_a_successful_sign_in_clears_the_emails_count(limited: str, db_client: TestClient) -> None:
    _signup(db_client)
    assert [_login(db_client, password=WRONG) for _ in range(9)] == [401] * 9
    assert _login(db_client) == 200
    assert [_login(db_client, password=WRONG) for _ in range(10)] == [401] * 10


def test_one_address_cannot_make_more_than_ten_accounts_an_hour(
    limited: str, db_client: TestClient
) -> None:
    for n in range(ratelimit.SIGNUPS_PER_HOUR):
        _signup(db_client, f"owner{n}@example.com")
    body = {"email": "one-more@example.com", "password": PASSWORD, "account_name": "Acme"}
    assert db_client.post("/auth/signup", json=body).status_code == 429


def test_a_wrong_current_password_on_password_change_is_limited(
    limited: str, db_client: TestClient
) -> None:
    token = _signup(db_client)
    body = {"current_password": "not mine", "new_password": "another good one"}
    statuses = [
        db_client.post("/auth/password", json=body, headers=_auth(token)).status_code
        for _ in range(ratelimit.PASSWORD_PER_USER + 1)
    ]
    assert statuses == [400] * ratelimit.PASSWORD_PER_USER + [429]


def test_with_redis_down_the_attempt_is_still_answered(
    monkeypatch: pytest.MonkeyPatch, db_client: TestClient
) -> None:
    monkeypatch.delenv(ratelimit.OFF_ENV)
    db_client.app.state.redis = redis.asyncio.Redis.from_url("redis://127.0.0.1:1/0")  # type: ignore[attr-defined]
    _signup(db_client)
    assert _login(db_client) == 200
    assert _login(db_client, password=WRONG) == 401


def test_parallel_guesses_cannot_get_past_the_limit(limited: str, db_client: TestClient) -> None:
    _signup(db_client)
    with ThreadPoolExecutor(30) as pool:
        codes = list(pool.map(lambda _: _login(db_client, password=WRONG), range(30)))
    assert codes.count(401) == ratelimit.SIGNIN_PER_EMAIL
    assert codes.count(429) == 30 - ratelimit.SIGNIN_PER_EMAIL
