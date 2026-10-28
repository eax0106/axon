"""Support chat, feedback and ratings, against a real database."""

from fastapi.testclient import TestClient

from .conftest import sql
from .helpers import account_id, add_call, add_member, signup, staff


def test_a_chat_message_is_answered_by_staff_in_that_accounts_thread_only(
    db_client: TestClient, migrated_url: str
) -> None:
    owner = signup(db_client)
    member = add_member(db_client, migrated_url, owner)
    other = signup(db_client, email="other@example.com", account="Other")
    admin = staff(db_client, migrated_url)
    asked = db_client.post("/support/chat", json={"body": "Calls are not starting"}, headers=member)
    assert asked.status_code == 201 and asked.json()["from_staff"] is False
    db_client.post("/support/chat", json={"body": "Unrelated question"}, headers=other)

    acme = account_id(db_client, owner)
    answer = {"body": "Your number's KYC is pending; we have nudged the carrier."}
    replied = db_client.post(f"/admin/support/{acme}/reply", json=answer, headers=admin)
    assert replied.status_code == 201 and replied.json()["from_staff"] is True

    thread = db_client.get("/support/chat", headers=owner).json()
    assert [(m["from_staff"], m["body"]) for m in thread] == [
        (False, "Calls are not starting"),
        (True, answer["body"]),
    ]
    theirs = db_client.get("/support/chat", headers=other).json()
    assert [m["body"] for m in theirs] == ["Unrelated question"]
    bell = db_client.get("/notifications", headers=owner).json()["items"]
    assert [n["kind"] for n in bell] == ["support_reply"]
    assert db_client.get("/notifications", headers=other).json()["items"] == []
    stranger = db_client.post(
        "/admin/support/00000000-0000-0000-0000-000000000000/reply", json=answer, headers=admin
    )
    assert stranger.status_code == 404
    assert db_client.post("/support/chat", json={"body": ""}, headers=owner).status_code == 422


def test_feedback_is_stored(db_client: TestClient, migrated_url: str) -> None:
    owner = signup(db_client)
    sent = db_client.post(
        "/support/feedback", json={"body": "Love the Telugu voices"}, headers=owner
    )
    assert sent.status_code == 201 and sent.json()["kind"] == "feedback"
    assert sql(migrated_url, "SELECT body FROM support_messages") == "Love the Telugu voices"


def test_a_rating_is_1_to_5_and_names_one_of_the_accounts_own_calls(
    db_client: TestClient, migrated_url: str
) -> None:
    owner = signup(db_client)
    signup(db_client, email="other@example.com", account="Other")
    mine = add_call(migrated_url, account_id(db_client, owner))
    theirs_account = sql(
        migrated_url, "SELECT account_id FROM users WHERE email = 'other@example.com'"
    )
    theirs = add_call(migrated_url, theirs_account)
    for score in (0, 6):
        body = {"call_id": str(mine), "rating": score}
        assert db_client.post("/support/rating", json=body, headers=owner).status_code == 422
    foreign = {"call_id": str(theirs), "rating": 5}
    assert db_client.post("/support/rating", json=foreign, headers=owner).status_code == 404
    rated = db_client.post(
        "/support/rating",
        json={"call_id": str(mine), "rating": 2, "body": "It spoke too fast"},
        headers=owner,
    )
    assert rated.status_code == 201
    assert (rated.json()["rating"], rated.json()["call_id"]) == (2, str(mine))


def test_staff_see_everything_in_one_inbox(db_client: TestClient, migrated_url: str) -> None:
    owner = signup(db_client)
    other = signup(db_client, email="other@example.com", account="Other")
    admin = staff(db_client, migrated_url)
    db_client.post("/support/chat", json={"body": "help"}, headers=owner)
    db_client.post("/support/feedback", json={"body": "nice"}, headers=other)
    call = add_call(migrated_url, account_id(db_client, other))
    db_client.post("/support/rating", json={"call_id": str(call), "rating": 4}, headers=other)

    inbox = db_client.get("/admin/support", headers=admin).json()["items"]
    assert [(m["kind"], m["account_name"]) for m in inbox] == [
        ("rating", "Other"),
        ("feedback", "Other"),
        ("chat", "Acme"),
    ]
    ratings = db_client.get("/admin/support", params={"kind": "rating"}, headers=admin).json()
    assert [m["rating"] for m in ratings["items"]] == [4]
    acme = account_id(db_client, owner)
    only = db_client.get("/admin/support", params={"account_id": acme}, headers=admin).json()
    assert [m["body"] for m in only["items"]] == ["help"]
    assert db_client.get("/admin/support", headers=owner).status_code == 403
