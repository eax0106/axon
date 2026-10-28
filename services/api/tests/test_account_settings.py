"""Account settings (name, business name, call length) and the password, against a real database."""

from typing import Any

from fastapi.testclient import TestClient

from app.employees import runtime
from app.models import Employee

from .conftest import sql
from .helpers import (
    PASSWORD,
    add_member,
    live_employee,
    run_db,
    seed,
    signup,
    staff,
    support_session,
)

NEW_PASSWORD = "a much better passphrase"  # noqa: S105 - test credential


def test_members_read_the_settings_and_only_the_owner_changes_them(
    db_client: TestClient, migrated_url: str
) -> None:
    owner = signup(db_client)
    member = add_member(db_client, migrated_url, owner)
    read = db_client.get("/account/settings", headers=member)
    assert read.status_code == 200
    assert read.json() == {"name": "Acme", "business_name": None, "max_call_s": 600}

    change = {"name": " Acme Solar ", "business_name": "SunBright", "max_call_s": 300}
    assert db_client.put("/account/settings", json=change, headers=member).status_code == 403
    saved = db_client.put("/account/settings", json=change, headers=owner)
    assert saved.status_code == 200
    assert saved.json() == {"name": "Acme Solar", "business_name": "SunBright", "max_call_s": 300}
    assert db_client.get("/account/settings", headers=member).json() == saved.json()
    cleared = db_client.put(
        "/account/settings", json={**change, "business_name": " "}, headers=owner
    )
    assert cleared.json()["business_name"] is None


def test_the_call_length_is_10_seconds_to_60_minutes(
    db_client: TestClient, migrated_url: str
) -> None:
    owner = signup(db_client)
    for seconds, code in ((9, 422), (10, 200), (3600, 200), (3601, 422)):
        body = {"name": "Acme", "max_call_s": seconds}
        assert db_client.put("/account/settings", json=body, headers=owner).status_code == code


def test_the_call_length_reaches_every_call_plan(db_client: TestClient, migrated_url: str) -> None:
    seed(migrated_url)
    owner = signup(db_client)
    employee = live_employee(db_client, migrated_url, owner)
    body = {"name": "Acme", "max_call_s": 90}
    assert db_client.put("/account/settings", json=body, headers=owner).status_code == 200

    async def work(factory: Any) -> runtime.CallPlan | None:
        async with factory() as session:
            row = await session.get(Employee, employee)
            return await runtime.plan_for(session, row)

    plan = run_db(migrated_url, work)
    assert plan is not None and plan.max_call_s == 90


def test_a_password_change_signs_out_every_older_session(
    db_client: TestClient, migrated_url: str
) -> None:
    first = signup(db_client)
    login = {"email": "owner@example.com", "password": PASSWORD}
    token = db_client.post("/auth/login", json=login).json()["access_token"]
    second = {"Authorization": f"Bearer {token}"}  # the same person on another device

    wrong = {"current_password": "not it at all", "new_password": NEW_PASSWORD}
    assert db_client.post("/auth/password", json=wrong, headers=first).status_code == 400
    short = {"current_password": PASSWORD, "new_password": "short"}
    assert db_client.post("/auth/password", json=short, headers=first).status_code == 422

    body = {"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    changed = db_client.post("/auth/password", json=body, headers=first)
    assert changed.status_code == 200
    fresh = {"Authorization": f"Bearer {changed.json()['access_token']}"}
    assert db_client.get("/accounts/me", headers=fresh).status_code == 200
    for old in (first, second):
        assert db_client.get("/accounts/me", headers=old).status_code == 401
    assert db_client.post("/auth/login", json=login).status_code == 401
    login["password"] = NEW_PASSWORD
    assert db_client.post("/auth/login", json=login).status_code == 200
    audit = "SELECT count(*) FROM audit_log WHERE action = 'password'"
    assert sql(migrated_url, audit) == 1


def test_a_support_session_cannot_change_the_password_or_make_an_api_key(
    db_client: TestClient, migrated_url: str
) -> None:
    signup(db_client)
    staff(db_client, migrated_url)
    support = support_session(migrated_url, "owner@example.com")
    assert db_client.get("/account/settings", headers=support).status_code == 200
    body = {"current_password": PASSWORD, "new_password": NEW_PASSWORD}
    assert db_client.post("/auth/password", json=body, headers=support).status_code == 403
    key = db_client.post("/developer/keys", json={"name": "zapier"}, headers=support)
    assert key.status_code == 403
    assert sql(migrated_url, "SELECT count(*) FROM api_keys") == 0


def test_a_support_session_cannot_take_a_credential_or_send_the_data_anywhere_new(
    db_client: TestClient, migrated_url: str
) -> None:
    """The lead-intake secret, webhooks, an employee's result webhook and actions, and a Google
    connection outlive the session and let calls be placed or carry the account's calls and leads
    out, so only the account's own people take or set them."""
    seed(migrated_url)
    owner = signup(db_client)
    staff(db_client, migrated_url)
    support = support_session(migrated_url, "owner@example.com")
    hook = {"url": "https://hooks.example.com/axon", "events": ["call.completed"]}
    mine = db_client.post("/developer/webhooks", json=hook, headers=owner)
    assert mine.status_code == 201
    employee = db_client.post(
        "/employees", json={"channel": "instant", "name": "Asha"}, headers=owner
    )
    eid = employee.json()["id"]
    elsewhere = {"url": "https://collector.example.net/x"}
    google = {"code": "c", "state": "s", "redirect_uri": "https://app.example.com/cb"}
    reveal = f"/employees/{eid}/instant/secret/reveal"
    secret = db_client.post(reveal, headers=owner).json()["secret"]
    refused = [
        db_client.post("/developer/webhooks", json={**hook, **elsewhere}, headers=support),
        db_client.patch(
            f"/developer/webhooks/{mine.json()['id']}", json=elsewhere, headers=support
        ),
        db_client.put(f"/employees/{eid}/webhook", json=elsewhere, headers=support),
        db_client.put(f"/employees/{eid}/actions", json={"actions": []}, headers=support),
        db_client.post("/integrations/google/connect", json=google, headers=support),
        db_client.post(reveal, headers=support),
        db_client.post(f"/employees/{eid}/instant/secret/rotate", headers=support),
    ]
    assert [r.status_code for r in refused] == [403] * 7
    assert [r.json()["detail"] for r in refused] == ["not allowed in a support session"] * 7
    assert sql(migrated_url, "SELECT string_agg(url, ',') FROM webhook_endpoints") == hook["url"]
    assert db_client.get(f"/employees/{eid}/webhook", headers=owner).json() == {"webhook": None}
    assert sql(migrated_url, "SELECT count(*) FROM google_connections") == 0
    assert db_client.post(reveal, headers=owner).json()["secret"] == secret  # not rotated
    assert db_client.get("/developer/webhooks", headers=support).status_code == 200  # reads stay
