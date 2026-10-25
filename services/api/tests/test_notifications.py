import pytest
from fastapi.testclient import TestClient

from .conftest import sql
from .helpers import signup


@pytest.fixture
def api(db_client: TestClient) -> TestClient:
    return db_client


def add(url: str, account: object, n: int, kind: str = "callback_scheduled") -> list[str]:
    ids = []
    for i in range(n):
        ids.append(
            str(
                sql(
                    url,
                    "INSERT INTO notifications (account_id, kind, title, body, created_at)"
                    " VALUES (:a, :k, :t, 'b', now() + make_interval(secs => :i)) RETURNING id",
                    {"a": account, "k": kind, "t": f"n{i}", "i": float(i)},
                )
            )
        )
    return ids


def account_of(api: TestClient, owner: dict[str, str]) -> str:
    return str(api.get("/accounts/me", headers=owner).json()["account"]["id"])


def test_list_has_the_unread_count_and_newest_first(api: TestClient, migrated_url: str) -> None:
    owner = signup(api)
    add(migrated_url, account_of(api, owner), 3)
    body = api.get("/notifications", headers=owner).json()
    assert body["unread_count"] == 3 and [n["title"] for n in body["items"]] == ["n2", "n1", "n0"]
    assert all(n["read"] is False for n in body["items"])
    assert len(api.get("/notifications?limit=2", headers=owner).json()["items"]) == 2
    assert api.get("/notifications?limit=0", headers=owner).status_code == 422


def test_marking_one_or_all_read(api: TestClient, migrated_url: str) -> None:
    owner = signup(api)
    first, *_ = add(migrated_url, account_of(api, owner), 3)
    assert api.post(f"/notifications/{first}/read", headers=owner).status_code == 204
    assert api.post(f"/notifications/{first}/read", headers=owner).status_code == 204  # idempotent
    body = api.get("/notifications", headers=owner).json()
    assert body["unread_count"] == 2 and sum(n["read"] for n in body["items"]) == 1
    assert len(api.get("/notifications?unread_only=true", headers=owner).json()["items"]) == 2
    assert api.post("/notifications/read-all", headers=owner).status_code == 204
    assert api.get("/notifications", headers=owner).json()["unread_count"] == 0


def test_notifications_belong_to_one_account(api: TestClient, migrated_url: str) -> None:
    owner, other = signup(api), signup(api, "b@example.com", "B")
    theirs = add(migrated_url, account_of(api, owner), 2)
    assert api.get("/notifications", headers=other).json() == {"unread_count": 0, "items": []}
    assert api.post(f"/notifications/{theirs[0]}/read", headers=other).status_code == 404
    assert api.post("/notifications/read-all", headers=other).status_code == 204
    assert api.get("/notifications", headers=owner).json()["unread_count"] == 2  # untouched
    assert api.get("/notifications").status_code == 401
