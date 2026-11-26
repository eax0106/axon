"""Staff sign in with a password and a second factor (B14 security review F6)."""

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import secretbox, totp
from app.auth import issue_token
from app.models import User
from app.second_factor import RECOVERY_CODES, TRIES_PER_USER

from .conftest import sql
from .helpers import PASSWORD, signup, staff_session
from .test_auth_rate_limit import limited  # noqa: F401 - fixture

STAFF = "staff@alterx.in"


def _login(client: TestClient, email: str = STAFF) -> dict[str, Any]:
    response = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _make_staff(client: TestClient, url: str, email: str = STAFF) -> None:
    signup(client, email=email, account="ALTERX")
    sql(url, "UPDATE users SET is_platform_admin = true WHERE email = :e", {"e": email})


def _enrol(client: TestClient, email: str = STAFF) -> tuple[str, dict[str, Any]]:
    """Sign in for the first time as staff and set up the app; the seed and the answer."""
    challenge = _login(client, email)["challenge"]
    seed = client.post("/auth/second-factor/enrol", json={"challenge": challenge}).json()["secret"]
    done = client.post(
        "/auth/second-factor/confirm",
        json={"challenge": challenge, "code": totp.code_at(seed, time.time())},
    )
    assert done.status_code == 200, done.text
    return seed, done.json()


def _verify(client: TestClient, code: str, email: str = STAFF) -> Any:
    challenge = _login(client, email)["challenge"]
    return client.post("/auth/second-factor/verify", json={"challenge": challenge, "code": code})


def _last_step_back(url: str, email: str = STAFF) -> None:
    """Forget the last code used, so the same 30 seconds can sign in again in a test."""
    sql(url, "UPDATE users SET totp_last_step = NULL WHERE email = :e", {"e": email})


def test_an_owner_signs_in_with_a_password_alone(db_client: TestClient) -> None:
    signup(db_client, email="owner@acme.in")
    body = _login(db_client, "owner@acme.in")
    assert body["access_token"] and body["second_factor"] is None and body["challenge"] is None


def test_the_first_staff_sign_in_must_set_up_the_app_and_then_opens_the_console(
    db_client: TestClient, migrated_url: str
) -> None:
    _make_staff(db_client, migrated_url)
    first = _login(db_client)
    assert first["access_token"] is None and first["second_factor"] == "enrol"
    # The challenge is not a session: no route but the second factor's accepts it.
    assert db_client.get("/accounts/me", headers=_bearer(first["challenge"])).status_code == 401
    assert db_client.get("/admin/accounts", headers=_bearer(first["challenge"])).status_code == 401

    start = db_client.post("/auth/second-factor/enrol", json={"challenge": first["challenge"]})
    seed, uri = start.json()["secret"], start.json()["otpauth_uri"]
    reload = db_client.post("/auth/second-factor/enrol", json={"challenge": first["challenge"]})
    assert reload.json()["secret"] == seed  # a reload shows the same key, not a new one
    assert uri.startswith("otpauth://totp/Axon%3Astaff%40alterx.in?secret=" + seed)
    stored = sql(migrated_url, "SELECT totp_secret FROM users WHERE email = :e", {"e": STAFF})
    assert stored != seed and secretbox.unseal(stored) == seed  # kept encrypted

    wrong = db_client.post(
        "/auth/second-factor/confirm", json={"challenge": first["challenge"], "code": "000000"}
    )
    assert wrong.status_code == 401
    assert _login(db_client)["second_factor"] == "enrol"  # not set up until a code proves it

    done = db_client.post(
        "/auth/second-factor/confirm",
        json={"challenge": first["challenge"], "code": totp.code_at(seed, time.time())},
    )
    assert done.status_code == 200, done.text
    codes = done.json()["recovery_codes"]
    assert len(set(codes)) == RECOVERY_CODES
    hashes = sql(
        migrated_url,
        "SELECT array_to_string(recovery_code_hashes, ',') FROM users WHERE email = :e",
        {"e": STAFF},
    )
    assert not any(c in hashes for c in codes)  # only their hashes are kept
    session = _bearer(done.json()["access_token"])
    assert db_client.get("/admin/accounts", headers=session).status_code == 200
    assert db_client.get("/accounts/me", headers=session).json()["user"]["second_factor"] is True
    again = db_client.post("/auth/second-factor/enrol", json={"challenge": first["challenge"]})
    assert again.status_code == 409  # set up once; a lost phone is reset by another staff member
    user = sql(migrated_url, "SELECT id::text FROM users WHERE email = :e", {"e": STAFF})
    log = "SELECT string_agg(action, ',') FROM audit_log WHERE target_id = :t"
    assert sql(migrated_url, log, {"t": user}) == "second_factor_enrolled"


def test_after_set_up_every_staff_sign_in_needs_a_fresh_code_or_one_recovery_code(
    db_client: TestClient, migrated_url: str
) -> None:
    _make_staff(db_client, migrated_url)
    seed, enrolled = _enrol(db_client)
    assert _login(db_client)["second_factor"] == "verify"
    code = totp.code_at(seed, time.time())
    assert _verify(db_client, code).status_code == 401  # the code used to enrol is spent
    assert _verify(db_client, "123456" if code != "123456" else "654321").status_code == 401

    recovery = enrolled["recovery_codes"][0]
    used = _verify(db_client, recovery.upper().replace("-", " "))  # typed loosely still works
    assert used.status_code == 200
    assert (
        db_client.get("/admin/accounts", headers=_bearer(used.json()["access_token"])).status_code
        == 200
    )
    assert _verify(db_client, recovery).status_code == 401  # once only
    assert _verify(db_client, enrolled["recovery_codes"][1]).status_code == 200

    _last_step_back(migrated_url)
    fresh = _verify(db_client, totp.code_at(seed, time.time()))
    assert fresh.status_code == 200
    assert _verify(db_client, totp.code_at(seed, time.time())).status_code == 401  # no replay


def test_a_staff_session_without_the_second_factor_cannot_open_the_console(
    db_client: TestClient, migrated_url: str
) -> None:
    """A session from before this shipped, or from before the user was made staff."""
    headers = signup(db_client, email=STAFF, account="ALTERX")
    sql(migrated_url, "UPDATE users SET is_platform_admin = true")
    refused = db_client.get("/admin/accounts", headers=headers)
    assert refused.status_code == 403 and "second factor" in refused.json()["detail"]
    assert db_client.get("/accounts/me", headers=headers).status_code == 200  # their own account


def test_a_challenge_dies_with_a_password_change_or_when_the_user_stops_being_staff(
    db_client: TestClient, migrated_url: str
) -> None:
    _make_staff(db_client, migrated_url)
    challenge = _login(db_client)["challenge"]
    sql(migrated_url, "UPDATE users SET is_platform_admin = false")
    assert (
        db_client.post("/auth/second-factor/enrol", json={"challenge": challenge}).status_code
        == 401
    )
    sql(migrated_url, "UPDATE users SET is_platform_admin = true")
    sql(migrated_url, "UPDATE users SET tokens_valid_after = now()")
    assert (
        db_client.post("/auth/second-factor/enrol", json={"challenge": challenge}).status_code
        == 401
    )
    user = sql(migrated_url, "SELECT id FROM users")
    session = issue_token(User(id=user))  # an ordinary session is not a challenge either
    assert (
        db_client.post("/auth/second-factor/enrol", json={"challenge": session}).status_code == 401
    )


def test_staff_keep_the_second_factor_across_a_password_change(
    db_client: TestClient, migrated_url: str
) -> None:
    _make_staff(db_client, migrated_url)
    _, enrolled = _enrol(db_client)
    changed = db_client.post(
        "/auth/password",
        json={"current_password": PASSWORD, "new_password": "another long one"},
        headers=_bearer(enrolled["access_token"]),
    )
    assert changed.status_code == 200
    assert (
        db_client.get(
            "/admin/accounts", headers=_bearer(changed.json()["access_token"])
        ).status_code
        == 200
    )


def test_another_staff_member_resets_a_lost_second_factor_and_it_is_logged(
    db_client: TestClient, migrated_url: str
) -> None:
    _make_staff(db_client, migrated_url)
    _, enrolled = _enrol(db_client)
    lost = sql(migrated_url, "SELECT id FROM users WHERE email = :e", {"e": STAFF})
    signup(db_client, email="lead@alterx.in", account="ALTERX ops")
    lead = staff_session(migrated_url, "lead@alterx.in")
    lead_id = sql(migrated_url, "SELECT id FROM users WHERE email = 'lead@alterx.in'")

    home = sql(migrated_url, "SELECT account_id FROM users WHERE id = :u", {"u": lost})
    detail = db_client.get(f"/admin/accounts/{home}", headers=lead)
    assert detail.json()["users"][0] | {"id": None} == {
        "id": None, "email": STAFF, "role": "owner", "staff": True, "second_factor": True,
    }  # fmt: skip

    own = db_client.post(f"/admin/users/{lead_id}/second-factor/reset", headers=lead)
    assert own.status_code == 409
    owner = signup(db_client, email="owner@acme.in")
    customer = sql(migrated_url, "SELECT id FROM users WHERE email = 'owner@acme.in'")
    assert (
        db_client.post(f"/admin/users/{customer}/second-factor/reset", headers=lead).status_code
        == 404
    )
    assert (
        db_client.post(f"/admin/users/{lost}/second-factor/reset", headers=owner).status_code == 403
    )

    assert (
        db_client.post(f"/admin/users/{lost}/second-factor/reset", headers=lead).status_code == 204
    )
    # Every session they had is signed out, and the next sign-in sets up a new app.
    assert (
        db_client.get("/accounts/me", headers=_bearer(enrolled["access_token"])).status_code == 401
    )
    assert _login(db_client)["second_factor"] == "enrol"
    assert _verify(db_client, enrolled["recovery_codes"][0]).status_code == 409
    log = "SELECT actor_user_id FROM audit_log WHERE action = 'second_factor_reset'"
    log += " AND target_id = :t"
    assert sql(migrated_url, log, {"t": str(lost)}) == lead_id


def test_codes_are_limited_per_staff_member(
    limited: str,  # noqa: F811 - fixture
    db_client: TestClient,
    migrated_url: str,
) -> None:
    _make_staff(db_client, migrated_url)
    seed, _ = _enrol(db_client)
    answers = [_verify(db_client, "000000").status_code for _ in range(TRIES_PER_USER)]
    assert answers == [401] * TRIES_PER_USER
    _last_step_back(migrated_url)
    assert (
        _verify(db_client, totp.code_at(seed, time.time())).status_code == 429
    )  # even a right one


def test_a_signed_in_staff_session_is_not_downgraded_by_a_support_session(
    db_client: TestClient, migrated_url: str
) -> None:
    """A support session opened from a second-factor staff session still cannot reach /admin."""
    _make_staff(db_client, migrated_url)
    _, enrolled = _enrol(db_client)
    signup(db_client, email="owner@acme.in")
    acme = sql(migrated_url, "SELECT account_id FROM users WHERE email = 'owner@acme.in'")
    opened = db_client.post(
        f"/admin/accounts/{acme}/impersonate",
        json={"reason": "checking a report"},
        headers=_bearer(enrolled["access_token"]),
    )
    support = _bearer(opened.json()["access_token"])
    assert db_client.get("/admin/accounts", headers=support).status_code == 403


@pytest.mark.parametrize("path", ["enrol", "confirm", "verify"])
def test_the_second_factor_routes_refuse_a_missing_or_forged_challenge(
    db_client: TestClient, path: str
) -> None:
    body = {"challenge": "not-a-token", "code": "123456"}
    assert db_client.post(f"/auth/second-factor/{path}", json=body).status_code == 401
    assert db_client.post(f"/auth/second-factor/{path}", json={}).status_code == 422
