"""The do-not-call list through the API, against a real database."""

from typing import Any

from fastapi.testclient import TestClient

from .conftest import sql
from .helpers import add_call, add_lead, add_member, signup


def listed(client: TestClient, headers: dict[str, str], **query: Any) -> dict[str, Any]:
    response = client.get("/dnc", params=query, headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_one_number_is_added_normalised_with_its_reason_once(
    db_client: TestClient, migrated_url: str
) -> None:
    owner = signup(db_client)
    member = add_member(db_client, migrated_url, owner)
    first = db_client.post(
        "/dnc", json={"phone": "98765 43210", "reason": "asked by email"}, headers=member
    )
    assert first.status_code == 201
    entry = first.json()
    assert (entry["phone"], entry["source"], entry["reason"]) == (
        "+919876543210",
        "manual",
        "asked by email",
    )
    again = db_client.post("/dnc", json={"phone": "+91 98765-43210"}, headers=owner)
    assert again.status_code == 200 and again.json()["id"] == entry["id"]
    assert again.json()["reason"] == "asked by email"  # the first entry stands
    assert listed(db_client, owner)["total"] == 1
    bad = db_client.post("/dnc", json={"phone": "12345"}, headers=owner)
    assert bad.status_code == 422


def test_many_numbers_at_once_say_what_happened_to_each(
    db_client: TestClient, migrated_url: str
) -> None:
    owner = signup(db_client)
    db_client.post("/dnc", json={"phone": "9876543210"}, headers=owner)
    phones = ["9876543210", "9876543211", "+919876543212", "98765 43212", "hello", "1234"]
    result = db_client.post(
        "/dnc/bulk", json={"phones": phones, "reason": "old list"}, headers=owner
    )
    assert result.status_code == 200
    assert result.json() == {"added": 2, "already_listed": 1, "invalid": 2}
    items = listed(db_client, owner)["items"]
    assert sorted((i["phone"], i["source"]) for i in items) == [
        ("+919876543210", "manual"),
        ("+919876543211", "bulk"),
        ("+919876543212", "bulk"),
    ]
    many = [f"9{n:09d}" for n in range(1_000, 3_500)]  # more rows than one insert carries
    big = db_client.post("/dnc/bulk", json={"phones": many}, headers=owner)
    assert big.json() == {"added": 2_500, "already_listed": 0, "invalid": 0}


def test_the_list_is_searched_and_paged(db_client: TestClient, migrated_url: str) -> None:
    owner = signup(db_client)
    phones = [f"98765432{i:02d}" for i in range(10, 15)]
    db_client.post("/dnc/bulk", json={"phones": phones}, headers=owner)
    page = listed(db_client, owner, limit=2, offset=2)
    assert (page["total"], len(page["items"])) == (5, 2)
    everything = listed(db_client, owner, limit=10)["items"]
    assert [i["phone"] for i in everything[2:4]] == [i["phone"] for i in page["items"]]
    found = listed(db_client, owner, q="432 13")
    assert [i["phone"] for i in found["items"]] == ["+919876543213"]
    assert listed(db_client, owner, q="%")["total"] == 5  # nothing to search for: everything


def test_only_the_owner_removes_a_number(db_client: TestClient, migrated_url: str) -> None:
    owner = signup(db_client)
    member = add_member(db_client, migrated_url, owner)
    entry = db_client.post("/dnc", json={"phone": "9876543210"}, headers=owner).json()
    assert db_client.delete(f"/dnc/{entry['id']}", headers=member).status_code == 403
    assert db_client.delete(f"/dnc/{entry['id']}", headers=owner).status_code == 204
    assert db_client.delete(f"/dnc/{entry['id']}", headers=owner).status_code == 404
    assert listed(db_client, owner)["total"] == 0


def test_adding_a_number_cancels_the_calls_waiting_for_it(
    db_client: TestClient, migrated_url: str
) -> None:
    owner = signup(db_client)
    account = sql(migrated_url, "SELECT account_id FROM users")
    ravi = add_lead(migrated_url, account, "+919876543210", "Ravi")
    asha = add_lead(migrated_url, account, "+919876543211", "Asha")
    waiting = add_call(migrated_url, account, lead=ravi, status="queued")
    other = add_call(migrated_url, account, lead=asha, status="queued")
    done = add_call(migrated_url, account, lead=ravi, status="completed")
    db_client.post("/dnc", json={"phone": "9876543210"}, headers=owner)
    status = "SELECT status FROM calls WHERE id = :c"
    assert sql(migrated_url, status, {"c": waiting}) == "canceled"
    assert sql(migrated_url, status, {"c": other}) == "queued"
    assert sql(migrated_url, status, {"c": done}) == "completed"
    db_client.post("/dnc/bulk", json={"phones": ["9876543211"]}, headers=owner)
    assert sql(migrated_url, status, {"c": other}) == "canceled"


def test_each_account_sees_and_changes_only_its_own_list(
    db_client: TestClient, migrated_url: str
) -> None:
    mine = signup(db_client)
    theirs = signup(db_client, email="other@example.com", account="Other")
    entry = db_client.post("/dnc", json={"phone": "9876543210"}, headers=mine).json()
    assert listed(db_client, theirs)["total"] == 0
    assert db_client.delete(f"/dnc/{entry['id']}", headers=theirs).status_code == 404
    # The same number on another account's list is a separate entry.
    assert db_client.post("/dnc", json={"phone": "9876543210"}, headers=theirs).status_code == 201
    account = sql(migrated_url, "SELECT account_id FROM users WHERE email = 'other@example.com'")
    lead = add_lead(migrated_url, account, "+919876543211", "Asha")
    call = add_call(migrated_url, account, lead=lead, status="queued")
    db_client.post("/dnc", json={"phone": "9876543211"}, headers=mine)
    assert sql(migrated_url, "SELECT status FROM calls WHERE id = :c", {"c": call}) == "queued"
