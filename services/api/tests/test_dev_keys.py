from fastapi.testclient import TestClient

from app.developer import keys

from .conftest import sql
from .developer_support import bearer, make_key
from .helpers import add_member, signup


def test_a_key_is_shown_once_and_only_its_hash_is_stored(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    created = api.post("/developer/keys", json={"name": "n8n"}, headers=owner)
    assert created.status_code == 201
    key = created.json()["key"]
    assert key.startswith(keys.PREFIX) and len(key) > 40
    assert created.json()["prefix"] == key[: keys.SHOWN]

    row = sql(
        migrated_url,
        "SELECT to_jsonb(k)::text FROM api_keys k WHERE id = :i",
        {"i": created.json()["id"]},
    )
    assert key not in row and keys.digest(key) in row

    listed = api.get("/developer/keys", headers=owner).json()
    assert [k["name"] for k in listed] == ["n8n"]
    assert key not in str(listed) and "key" not in listed[0]


def test_only_the_owner_makes_or_revokes_keys_but_a_member_can_look(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    member = add_member(api, migrated_url, owner)
    assert api.post("/developer/keys", json={"name": "x"}, headers=member).status_code == 403
    made = api.post("/developer/keys", json={"name": "ok"}, headers=owner).json()
    assert api.delete(f"/developer/keys/{made['id']}", headers=member).status_code == 403
    assert len(api.get("/developer/keys", headers=member).json()) == 1


def test_the_number_of_active_keys_is_capped_and_revoking_frees_a_place(
    api: TestClient,
) -> None:
    owner = signup(api)
    ids = [
        api.post("/developer/keys", json={"name": f"k{i}"}, headers=owner).json()["id"]
        for i in range(keys.MAX_ACTIVE_KEYS)
    ]
    full = api.post("/developer/keys", json={"name": "one more"}, headers=owner)
    assert full.status_code == 409
    assert api.delete(f"/developer/keys/{ids[0]}", headers=owner).status_code == 204
    assert api.post("/developer/keys", json={"name": "now"}, headers=owner).status_code == 201


def test_a_revoked_key_stops_working_at_once_and_stays_in_the_list(api: TestClient) -> None:
    owner = signup(api)
    key = make_key(api, owner)
    assert api.get("/v1/account", headers=bearer(key)).status_code == 200
    key_id = api.get("/developer/keys", headers=owner).json()[0]["id"]
    assert api.delete(f"/developer/keys/{key_id}", headers=owner).status_code == 204
    assert api.delete(f"/developer/keys/{key_id}", headers=owner).status_code == 204  # again
    refused = api.get("/v1/account", headers=bearer(key))
    assert refused.status_code == 401
    shown = api.get("/developer/keys", headers=owner).json()[0]
    assert shown["revoked_at"] is not None


def test_the_public_api_refuses_a_missing_malformed_unknown_or_dashboard_token(
    api: TestClient,
) -> None:
    owner = signup(api)
    for headers in (
        {},
        {"Authorization": "Bearer"},
        {"Authorization": "Bearer nonsense"},
        {"Authorization": f"Bearer {keys.PREFIX}{'a' * 43}"},
        {"Authorization": "Basic abc"},
        owner,  # a dashboard login token is not an API key
    ):
        response = api.get("/v1/account", headers=headers)
        assert response.status_code == 401, headers
        assert response.headers["www-authenticate"] == "Bearer"


def test_using_a_key_records_when_it_was_last_used(api: TestClient) -> None:
    owner = signup(api)
    key = make_key(api, owner)
    assert api.get("/developer/keys", headers=owner).json()[0]["last_used_at"] is None
    api.get("/v1/account", headers=bearer(key))
    assert api.get("/developer/keys", headers=owner).json()[0]["last_used_at"] is not None


def test_a_key_only_opens_its_own_account(api: TestClient) -> None:
    first = signup(api, email="a@example.com", account="First")
    second = signup(api, email="b@example.com", account="Second")
    assert api.get("/v1/account", headers=bearer(make_key(api, first))).json()["name"] == "First"
    assert api.get("/v1/account", headers=bearer(make_key(api, second))).json()["name"] == "Second"
