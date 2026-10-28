"""Admin console: who may use it, the accounts, support sessions and credit adjustments."""

import uuid
from decimal import Decimal
from typing import Any

import jwt
from fastapi.testclient import TestClient

from app.main import app

from .conftest import TEST_JWT_SECRET, sql
from .helpers import account_id, add_member, signup, staff


def bearer(response: Any) -> dict[str, str]:
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_every_admin_route_refuses_anyone_but_platform_staff(
    db_client: TestClient, migrated_url: str
) -> None:
    owner = signup(db_client)
    member = add_member(db_client, migrated_url, owner)
    paths = {p: ops for p, ops in app.openapi()["paths"].items() if p.startswith("/admin")}
    assert len(paths) >= 20
    for template, operations in paths.items():
        path = template.replace("{vendor}", "sarvam")
        for name in ("account_id", "voice_id", "number_id", "entry_id"):
            path = path.replace(f"{{{name}}}", str(uuid.uuid4()))
        for method in operations:
            for who in (owner, member, {}):
                got = db_client.request(method, path, headers=who, json={}).status_code
                assert got == (403 if who else 401), (method, path, got)


def test_accounts_are_listed_searched_and_shown(db_client: TestClient, migrated_url: str) -> None:
    acme = signup(db_client)
    signup(db_client, email="ravi@sunbright.in", account="SunBright Solar")
    admin = staff(db_client, migrated_url)
    listed = db_client.get("/admin/accounts", headers=admin).json()
    assert listed["total"] == 3
    assert [a["name"] for a in listed["items"]] == ["ALTERX", "SunBright Solar", "Acme"]
    by_name = db_client.get("/admin/accounts", params={"q": "sunbright"}, headers=admin).json()
    assert [a["owner_email"] for a in by_name["items"]] == ["ravi@sunbright.in"]
    by_email = db_client.get("/admin/accounts", params={"q": "OWNER@example"}, headers=admin)
    assert [a["name"] for a in by_email.json()["items"]] == ["Acme"]
    paged = db_client.get("/admin/accounts", params={"limit": 1, "offset": 1}, headers=admin)
    assert [a["name"] for a in paged.json()["items"]] == ["SunBright Solar"]

    detail = db_client.get(f"/admin/accounts/{account_id(db_client, acme)}", headers=admin).json()
    assert detail["name"] == "Acme" and [u["email"] for u in detail["users"]] == [
        "owner@example.com"
    ]
    assert detail["ledger"][0]["kind"] == "bonus"  # the free signup credits
    missing = db_client.get(f"/admin/accounts/{uuid.uuid4()}", headers=admin)
    assert missing.status_code == 404


def test_a_support_session_needs_a_reason_and_logs_everything_it_changes(
    db_client: TestClient, migrated_url: str
) -> None:
    owner = signup(db_client)
    acme = account_id(db_client, owner)
    admin = staff(db_client, migrated_url)
    path = f"/admin/accounts/{acme}/impersonate"
    assert db_client.post(path, json={"reason": "hi"}, headers=admin).status_code == 422
    opened = db_client.post(path, json={"reason": "ticket 42: calls not starting"}, headers=admin)
    assert opened.status_code == 200 and opened.json()["expires_in"] == 1800
    support = bearer(opened)
    claims = jwt.decode(opened.json()["access_token"], TEST_JWT_SECRET, algorithms=["HS256"])
    assert abs(claims["exp"] - claims["iat"] - 30 * 60) < 1  # `exp` drops the fraction

    me = db_client.get("/accounts/me", headers=support).json()
    assert me["user"]["email"] == "owner@example.com" and me["account"]["id"] == acme
    change = {"name": "Acme", "business_name": "Acme Solar", "max_call_s": 120}
    assert db_client.put("/account/settings", json=change, headers=support).status_code == 200
    staff_id = sql(migrated_url, "SELECT id FROM users WHERE email = 'staff@alterx.in'")
    log = sql(
        migrated_url,
        "SELECT string_agg(action || ':' || coalesce(target_id, '') || ':'"
        " || coalesce(impersonator_user_id::text, actor_user_id::text), ',' ORDER BY id)"
        " FROM audit_log WHERE account_id = :a",
        {"a": acme},
    )
    assert log.split(",") == [
        f"impersonation_started:{acme}:{staff_id}",
        f"impersonated_request:PUT /account/settings:{staff_id}",
    ]
    reason = "SELECT data->>'reason' FROM audit_log WHERE action = 'impersonation_started'"
    assert sql(migrated_url, reason) == "ticket 42: calls not starting"

    assert db_client.get("/admin/accounts", headers=support).status_code == 403
    sql(migrated_url, "UPDATE users SET is_platform_admin = false WHERE id = :s", {"s": staff_id})
    assert db_client.get("/accounts/me", headers=support).status_code == 401


def test_a_staff_member_in_a_support_session_cannot_reach_the_admin_console(
    db_client: TestClient, migrated_url: str
) -> None:
    signup(db_client, email="lead@alterx.in", account="ALTERX ops")
    sql(migrated_url, "UPDATE users SET is_platform_admin = true")  # an account of staff
    admin = staff(db_client, migrated_url)
    target = sql(migrated_url, "SELECT account_id FROM users WHERE email = 'lead@alterx.in'")
    opened = db_client.post(
        f"/admin/accounts/{target}/impersonate", json={"reason": "checking a report"}, headers=admin
    )
    assert db_client.get("/admin/accounts", headers=bearer(opened)).status_code == 403


def test_a_credit_adjustment_is_posted_logged_and_never_below_zero(
    db_client: TestClient, migrated_url: str
) -> None:
    owner = signup(db_client)
    acme = account_id(db_client, owner)
    admin = staff(db_client, migrated_url)
    path = f"/admin/accounts/{acme}/credits"
    start = Decimal(
        str(sql(migrated_url, "SELECT credit_balance FROM accounts WHERE id = :a", {"a": acme}))
    )
    added = db_client.post(path, json={"amount": "250.50", "note": "goodwill"}, headers=admin)
    assert added.status_code == 200
    assert Decimal(added.json()["balance"]) == start + Decimal("250.50")
    too_much = {"amount": str(-(start + Decimal("251"))), "note": "take back"}
    assert db_client.post(path, json=too_much, headers=admin).status_code == 402
    taken = db_client.post(path, json={"amount": "-50", "note": "take back"}, headers=admin)
    assert Decimal(taken.json()["balance"]) == start + Decimal("200.50")
    assert (
        db_client.post(path, json={"amount": "0", "note": "nothing"}, headers=admin).status_code
        == 422
    )
    rows = sql(
        migrated_url,
        "SELECT string_agg(amount::numeric(12, 2) || ' ' || note, ',' ORDER BY id)"
        " FROM wallet_ledger WHERE kind = 'adjustment'",
    )
    assert rows == "250.50 goodwill,-50.00 take back"
    assert (
        sql(migrated_url, "SELECT count(*) FROM audit_log WHERE action = 'credits_adjusted'") == 2
    )
    balance = sql(migrated_url, "SELECT credit_balance FROM accounts WHERE id = :a", {"a": acme})
    assert Decimal(str(balance)) == start + Decimal("200.50")
