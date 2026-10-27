"""Callers nobody answered: the list, why, what became of the call-back, and the conversations."""

from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient

from .conftest import sql
from .dialing import Carrier
from .helpers import signup
from .inbound_support import CALLER, NOW, inbound_employee, ring
from .test_inbound_callback import CLOSED


def missed_list(client: TestClient, owner: dict[str, str], **query: str) -> dict[str, Any]:
    response = client.get("/inbound/missed", params=query, headers=owner)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_a_missed_caller_is_listed_with_the_reason_and_what_became_of_the_call_back(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    employee, owner = inbound_employee(api, migrated_url, settings=CLOSED)
    ring(migrated_url, fake, carrier_id="leg-1")
    listed = missed_list(api, owner)
    assert listed["total"] == 1
    (item,) = listed["items"]
    assert item["employee_id"] == employee and item["phone"] == CALLER
    assert item["code"] == "closed" and "opening hours" in item["reason"]
    assert item["auto_callback"]["state"] == "scheduled"
    assert item["auto_callback"]["at"] is not None and item["auto_callback"]["call_id"] is not None


def test_a_missed_caller_nobody_will_call_back_says_why_not(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    _, owner = inbound_employee(api, migrated_url, settings=CLOSED)
    ring(migrated_url, fake, carrier_id="leg-1")
    ring(migrated_url, fake, carrier_id="leg-2")  # the same caller, the same day
    first, second = sorted(missed_list(api, owner)["items"], key=lambda i: i["at"])
    assert first["auto_callback"]["state"] == "scheduled"
    assert second["auto_callback"] == {
        "state": "none",
        "at": None,
        "call_id": None,
        "not_made_because": "this caller was already called back today",
    }


def test_the_call_back_state_follows_the_call(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    _, owner = inbound_employee(api, migrated_url, settings=CLOSED)
    ring(migrated_url, fake)
    for status, state in [
        ("ringing", "calling"),
        ("completed", "answered"),
        ("no_answer", "not_answered"),
        ("canceled", "cancelled"),
    ]:
        sql(migrated_url, f"UPDATE calls SET status = '{status}' WHERE is_callback")  # noqa: S608
        assert missed_list(api, owner)["items"][0]["auto_callback"]["state"] == state


def test_answered_calls_are_not_missed_ones(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    _, owner = inbound_employee(api, migrated_url)
    ring(migrated_url, fake)
    assert missed_list(api, owner) == {"total": 0, "items": []}


def test_the_list_pages_newest_first_and_narrows_to_an_employee(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    employee, owner = inbound_employee(api, migrated_url, settings=CLOSED)
    for index, when in enumerate([NOW, NOW + timedelta(hours=1), NOW + timedelta(hours=2)]):
        ring(migrated_url, fake, carrier_id=f"leg-{index}", caller=f"+91987654321{index}", now=when)
    everything = missed_list(api, owner)
    assert everything["total"] == 3
    assert [i["phone"] for i in everything["items"]] == [
        "+919876543212",
        "+919876543211",
        "+919876543210",
    ]
    page = missed_list(api, owner, limit="1", offset="1")
    assert page["total"] == 3 and [i["phone"] for i in page["items"]] == ["+919876543211"]
    assert missed_list(api, owner, employee_id=employee)["total"] == 3
    assert missed_list(api, owner, employee_id="00000000-0000-0000-0000-000000000000")["total"] == 0


def test_nobody_sees_another_accounts_missed_callers(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    inbound_employee(api, migrated_url, settings=CLOSED)
    ring(migrated_url, fake)
    stranger = signup(api, "other@example.com", "Other")
    assert missed_list(api, stranger) == {"total": 0, "items": []}
    assert api.get("/inbound/missed").status_code == 401


def test_conversations_show_a_missed_call_with_its_reason_and_the_callers_number(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    _, owner = inbound_employee(api, migrated_url, settings=CLOSED)
    ring(migrated_url, fake, caller="+919000000001")
    sql(migrated_url, "UPDATE leads SET name = NULL")
    sql(migrated_url, "UPDATE calls SET lead_id = NULL")  # a caller we hold no lead for
    rows = api.get("/calls", headers=owner).json()["items"]
    row = next(r for r in rows if r["direction"] == "inbound")
    assert row["phone"] == "+919000000001" and "opening hours" in row["miss_reason"]
    assert row["status"] == "no_answer"
