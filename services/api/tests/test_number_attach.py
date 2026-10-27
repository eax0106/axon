"""One number per employee, one employee per number, and the channels a number carries."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth import issue_token
from app.models import User

from .conftest import sql
from .helpers import account_id, live_employee, seed, signup


@pytest.fixture
def api(db_client: TestClient, migrated_url: str) -> TestClient:
    seed(migrated_url)
    return db_client


def hire(api: TestClient, owner: dict[str, str]) -> str:
    return str(api.post("/employees", json={"channel": "bulk"}, headers=owner).json()["id"])


def rent(url: str, account: str, e164: str, status: str = "active") -> str:
    return str(
        sql(
            url,
            "INSERT INTO numbers (account_id, provider, e164, number_type, status)"
            " VALUES (:a, 'vobiz', :n, 'regular', :s) RETURNING id",
            {"a": account, "n": e164, "s": status},
        )
    )


def attach(api: TestClient, owner: dict[str, str], employee: str, number: str) -> Any:
    return api.put(f"/employees/{employee}/number", json={"number_id": number}, headers=owner)


def test_an_employee_gets_one_number_and_a_number_serves_one_employee(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    mine = account_id(api, owner)
    asha, ravi = hire(api, owner), hire(api, owner)
    first, second = (
        rent(migrated_url, mine, "+919100000001"),
        rent(migrated_url, mine, "+919100000002"),
    )
    got = attach(api, owner, asha, first)
    assert got.status_code == 200 and got.json()["employee_id"] == asha
    assert api.get(f"/employees/{asha}", headers=owner).json()["number_id"] == first
    twice = attach(api, owner, asha, second)  # a second number for the same employee
    assert twice.status_code == 409 and "already has a number" in twice.json()["detail"]
    shared = attach(api, owner, ravi, first)  # the same number for a second employee
    assert shared.status_code == 409 and "another employee" in shared.json()["detail"]
    assert [(n["e164"], n["employee_id"]) for n in api.get("/numbers", headers=owner).json()] == [
        ("+919100000001", asha),
        ("+919100000002", None),
    ]
    assert api.delete(f"/employees/{asha}/number", headers=owner).status_code == 200
    assert attach(api, owner, asha, second).status_code == 200  # free to take another now
    assert attach(api, owner, ravi, first).status_code == 200  # and the first is free to move


def test_only_an_active_number_can_be_attached(api: TestClient, migrated_url: str) -> None:
    owner = signup(api)
    mine = account_id(api, owner)
    employee = hire(api, owner)
    for status in ("grace", "released"):
        number = rent(
            migrated_url, mine, f"+91910000{'0001' if status == 'grace' else '0002'}", status
        )
        got = attach(api, owner, employee, number)
        assert got.status_code == 409 and status in got.json()["detail"]
    assert api.get(f"/employees/{employee}", headers=owner).json()["number_id"] is None


def test_attach_and_detach_stay_inside_the_account(api: TestClient, migrated_url: str) -> None:
    mine, theirs = signup(api), signup(api, "b@example.com", "B")
    their_number = rent(migrated_url, account_id(api, theirs), "+919100000003")
    my_employee = hire(api, mine)
    assert attach(api, mine, my_employee, their_number).status_code == 404  # not my number
    my_number = rent(migrated_url, account_id(api, mine), "+919100000004")
    assert attach(api, theirs, my_employee, my_number).status_code == 404  # not their employee
    attach(api, mine, my_employee, my_number)
    assert api.delete(f"/employees/{my_employee}/number", headers=theirs).status_code == 404
    assert api.get(f"/employees/{my_employee}", headers=mine).json()["number_id"] == my_number
    assert attach(api, mine, my_employee, "00000000-0000-0000-0000-000000000000").status_code == 409


def test_detaching_pauses_a_live_employee_and_leaves_the_rest(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    live = live_employee(api, migrated_url, owner)
    got = api.delete(f"/employees/{live}/number", headers=owner)
    assert got.status_code == 200 and got.json() == {"status": "paused"}
    assert (
        api.delete(f"/employees/{live}/number", headers=owner).status_code == 409
    )  # no number left
    assert api.post(f"/employees/{live}/activate", headers=owner).status_code == 409
    number = sql(migrated_url, "SELECT id FROM numbers")
    assert attach(api, owner, live, str(number)).status_code == 200
    assert api.post(f"/employees/{live}/activate", headers=owner).status_code == 200
    draft = hire(api, owner)
    spare = rent(migrated_url, account_id(api, owner), "+919100000005")
    attach(api, owner, draft, spare)
    assert api.delete(f"/employees/{draft}/number", headers=owner).json() == {"status": "draft"}


def test_channels_are_set_per_number_within_limits(api: TestClient, migrated_url: str) -> None:
    owner = signup(api)
    other = signup(api, "b@example.com", "B")
    number = rent(migrated_url, account_id(api, owner), "+919100000006")
    got = api.put(f"/numbers/{number}/channels", json={"channels": 5}, headers=owner)
    assert got.status_code == 200 and got.json()["channels"] == 5
    assert api.get("/numbers", headers=owner).json()[0]["channels"] == 5
    for channels in (0, 21, -1, "many"):
        bad = api.put(f"/numbers/{number}/channels", json={"channels": channels}, headers=owner)
        assert bad.status_code == 422, channels
    assert (
        api.put(f"/numbers/{number}/channels", json={"channels": 2}, headers=other).status_code
        == 404
    )
    released = rent(migrated_url, account_id(api, owner), "+919100000007", "released")
    assert (
        api.put(f"/numbers/{released}/channels", json={"channels": 2}, headers=owner).status_code
        == 409
    )
    assert sql(migrated_url, "SELECT channels FROM numbers WHERE id = :n", {"n": number}) == 5


def test_changing_numbers_is_for_the_owner_only(api: TestClient, migrated_url: str) -> None:
    owner = signup(api)
    mine = account_id(api, owner)
    member_id = sql(
        migrated_url,
        "INSERT INTO users (account_id, email, password_hash, role)"
        " VALUES (:a, 'm@example.com', 'x', 'member') RETURNING id",
        {"a": mine},
    )
    member = {"Authorization": f"Bearer {issue_token(User(id=member_id))}"}
    employee, number = hire(api, owner), rent(migrated_url, mine, "+919100000008")
    assert attach(api, member, employee, number).status_code == 403
    assert api.delete(f"/employees/{employee}/number", headers=member).status_code == 403
    assert (
        api.put(f"/numbers/{number}/channels", json={"channels": 2}, headers=member).status_code
        == 403
    )
    assert attach(api, {}, employee, number).status_code == 401
