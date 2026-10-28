"""The owner accepts a version of the terms; it is recorded on the account and in the audit log."""

from fastapi.testclient import TestClient

from .conftest import sql
from .helpers import add_member, signup, staff, support_session


def test_the_owner_accepts_a_version_and_everyone_in_the_account_can_read_it(
    db_client: TestClient, migrated_url: str
) -> None:
    owner = signup(db_client)
    member = add_member(db_client, migrated_url, owner)
    assert db_client.get("/account/terms", headers=member).json() == {
        "version": None,
        "accepted_at": None,
    }
    accepted = db_client.post("/account/terms", json={"version": " 2026-11 "}, headers=owner)
    assert accepted.status_code == 200
    assert accepted.json()["version"] == "2026-11"
    assert accepted.json()["accepted_at"]
    assert db_client.get("/account/terms", headers=member).json() == accepted.json()

    db_client.post("/account/terms", json={"version": "2027-01"}, headers=owner)
    kept = sql(
        migrated_url,
        "SELECT string_agg(target_id, ',' ORDER BY created_at) FROM audit_log"
        " WHERE action = 'terms_accepted'",
    )
    assert kept == "2026-11,2027-01"


def test_only_the_owner_accepts_never_a_member_or_staff_in_a_support_session(
    db_client: TestClient, migrated_url: str
) -> None:
    owner = signup(db_client)
    member = add_member(db_client, migrated_url, owner)
    staff(db_client, migrated_url)
    support = support_session(migrated_url, "owner@example.com")
    body = {"version": "2026-11"}
    assert db_client.post("/account/terms", json=body, headers=member).status_code == 403
    assert db_client.post("/account/terms", json=body, headers=support).status_code == 403
    assert db_client.get("/account/terms", headers=owner).json()["version"] is None


def test_a_blank_or_oversized_version_is_refused(db_client: TestClient) -> None:
    owner = signup(db_client)
    for version in ("", "v" * 41):
        assert (
            db_client.post("/account/terms", json={"version": version}, headers=owner).status_code
            == 422
        )
