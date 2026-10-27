"""Free calls ring a phone line too: a test call or the owner-phone code waits while every channel
of the number is on a call, so the paid calls the owner is running keep their line."""

from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.providers.telephony.vobiz import BASE_URL, VobizTelephony

from .conftest import sql
from .dialing import Carrier
from .helpers import live_employee, signup

PHONE = "+919876543210"


@pytest.fixture
def carrier(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Carrier, None]]:
    """The carrier the API itself talks to: every adapter the registry builds goes through it."""
    monkeypatch.setenv("VOBIZ_AUTH_ID", "MA_TEST")
    monkeypatch.setenv("VOBIZ_AUTH_TOKEN", "token")
    fake = Carrier()
    transport = httpx.MockTransport(fake.handler)
    monkeypatch.setattr(
        VobizTelephony,
        "_client",
        lambda self: httpx.AsyncClient(
            base_url=f"{BASE_URL}/Account/MA_TEST", headers=self._headers, transport=transport
        ),
    )
    yield fake, None


def busy_call(url: str, number: str, status: str = "in_progress") -> None:
    sql(
        url,
        "INSERT INTO calls (account_id, number_id, direction, channel, status)"
        " SELECT account_id, id, 'outbound', 'instant', :s FROM numbers WHERE id = :n",
        {"s": status, "n": number},
    )


def setup(api: TestClient, url: str) -> tuple[str, str, dict[str, str]]:
    owner = signup(api)
    employee = live_employee(api, url, owner)
    sql(
        url,
        "UPDATE accounts SET owner_phone = :p, owner_phone_verified_at = now()",
        {"p": PHONE},
    )
    return employee, str(sql(url, "SELECT id FROM numbers")), owner


def test_a_test_call_waits_while_every_channel_of_the_number_is_on_a_call(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    employee, number, owner = setup(api, migrated_url)
    busy_call(migrated_url, number)
    refused = api.post(f"/employees/{employee}/test-call", headers=owner)
    assert refused.status_code == 409 and "every channel" in refused.json()["detail"]
    assert fake.placed == [] and sql(migrated_url, "SELECT count(*) FROM calls WHERE is_test") == 0
    sql(migrated_url, "UPDATE numbers SET channels = 2")  # a second line is free
    placed = api.post(f"/employees/{employee}/test-call", headers=owner)
    assert placed.status_code == 202 and len(fake.placed) == 1


def test_an_answered_test_call_holds_a_channel_like_any_other_call(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    employee, number, owner = setup(api, migrated_url)
    first = api.post(f"/employees/{employee}/test-call", headers=owner)
    assert first.status_code == 202
    assert str(sql(migrated_url, "SELECT number_id FROM calls WHERE is_test")) == number
    sql(migrated_url, "UPDATE calls SET status = 'in_progress'")  # the owner picked up
    again = api.post(f"/employees/{employee}/test-call", headers=owner)
    assert again.status_code == 409
    sql(migrated_url, "UPDATE calls SET status = 'completed'")
    assert api.post(f"/employees/{employee}/test-call", headers=owner).status_code == 202


def test_a_browser_test_call_uses_no_phone_line(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    employee, number, owner = setup(api, migrated_url)
    busy_call(migrated_url, number)
    made = api.post(f"/employees/{employee}/web-test-call", headers=owner)
    assert made.status_code == 201


def test_the_code_call_waits_while_every_channel_is_busy(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    _, number, owner = setup(api, migrated_url)
    busy_call(migrated_url, number, "ringing")
    refused = api.post("/accounts/owner-phone", json={"phone": PHONE}, headers=owner)
    assert refused.status_code == 409 and "every channel" in refused.json()["detail"]
    assert fake.placed == [] and sql(migrated_url, "SELECT count(*) FROM phone_otps") == 0
    sql(migrated_url, "UPDATE calls SET status = 'completed'")
    assert (
        api.post("/accounts/owner-phone", json={"phone": PHONE}, headers=owner).status_code == 202
    )


def test_the_code_is_spoken_from_a_number_that_has_a_free_channel(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    _, busy, owner = setup(api, migrated_url)
    account = sql(migrated_url, "SELECT account_id FROM numbers")
    sql(
        migrated_url,
        "INSERT INTO numbers (account_id, provider, e164, number_type, status, created_at)"
        " VALUES (:a, 'vobiz', '+911400000002', 'regular', 'active', now() + interval '1 minute')",
        {"a": account},
    )
    busy_call(migrated_url, busy)
    sent: Any = api.post("/accounts/owner-phone", json={"phone": PHONE}, headers=owner)
    assert sent.status_code == 202
    assert fake.placed[0]["from"] == "911400000002"  # the first number is busy, the second is not
