"""Owners and members may turn on the authenticator-app second factor from Account settings."""

import time

from fastapi.testclient import TestClient

from app import totp
from app.second_factor import TRIES_PER_USER

from .conftest import sql
from .helpers import signup, staff_session, support_session
from .test_auth_rate_limit import limited  # noqa: F401 - fixture
from .test_second_factor import _bearer, _last_step_back, _login, _make_staff

OWNER = "owner@acme.in"


def _turn_on(client: TestClient, headers: dict[str, str]) -> tuple[str, list[str]]:
    seed = client.post("/auth/second-factor/setup", headers=headers).json()["secret"]
    again = client.post("/auth/second-factor/setup", headers=headers).json()["secret"]
    assert again == seed  # a reload shows the same key
    done = client.post(
        "/auth/second-factor/setup/confirm",
        json={"code": totp.code_at(seed, time.time())},
        headers=headers,
    )
    assert done.status_code == 200, done.text
    return seed, done.json()["recovery_codes"]


def _verify(client: TestClient, code: str, email: str = OWNER) -> int:
    challenge = _login(client, email)["challenge"]
    answer = client.post("/auth/second-factor/verify", json={"challenge": challenge, "code": code})
    return answer.status_code


def test_an_owner_turns_it_on_and_the_next_sign_in_asks_for_a_code(
    db_client: TestClient, migrated_url: str
) -> None:
    owner = signup(db_client, email=OWNER)
    assert db_client.get("/accounts/me", headers=owner).json()["user"]["two_factor"] is False
    wrong = db_client.post(
        "/auth/second-factor/setup/confirm", json={"code": "123456"}, headers=owner
    )
    assert wrong.status_code == 409  # nothing started yet

    seed, codes = _turn_on(db_client, owner)
    # This session carries on; sign-in now needs a code.
    assert db_client.get("/accounts/me", headers=owner).json()["user"]["two_factor"] is True
    signed = _login(db_client, OWNER)
    assert signed["access_token"] is None and signed["second_factor"] == "verify"
    _last_step_back(migrated_url, OWNER)
    assert _verify(db_client, totp.code_at(seed, time.time())) == 200
    # Each recovery code works once.
    assert _verify(db_client, codes[0]) == 200
    assert _verify(db_client, codes[0]) == 401
    assert _verify(db_client, codes[1]) == 200
    assert db_client.post("/auth/second-factor/setup", headers=owner).status_code == 409
    logged = "SELECT count(*) FROM audit_log WHERE action = 'second_factor_enrolled'"
    assert sql(migrated_url, logged) == 1


def test_a_member_can_turn_it_on_too(db_client: TestClient, migrated_url: str) -> None:
    signup(db_client, email=OWNER)
    signup(db_client, email="member@acme.in", account="Acme 2")
    sql(migrated_url, "UPDATE users SET role = 'member' WHERE email = 'member@acme.in'")
    member = _bearer(_login(db_client, "member@acme.in")["access_token"])
    _turn_on(db_client, member)
    assert _login(db_client, "member@acme.in")["second_factor"] == "verify"


def test_six_wrong_codes_in_15_minutes_are_blocked(
    limited: str,  # noqa: F811 - fixture
    db_client: TestClient,
    migrated_url: str,
) -> None:
    owner = signup(db_client, email=OWNER)
    seed, _ = _turn_on(db_client, owner)
    assert [_verify(db_client, "000000") for _ in range(TRIES_PER_USER)] == [401] * TRIES_PER_USER
    _last_step_back(migrated_url, OWNER)
    assert _verify(db_client, totp.code_at(seed, time.time())) == 429  # even a right one


def test_turning_it_off_needs_a_current_code_from_the_app(
    db_client: TestClient, migrated_url: str
) -> None:
    owner = signup(db_client, email=OWNER)
    seed, codes = _turn_on(db_client, owner)
    off = "/auth/second-factor/disable"
    assert db_client.post(off, json={"code": "000000"}, headers=owner).status_code == 401
    assert db_client.post(off, json={"code": codes[0]}, headers=owner).status_code == 401
    _last_step_back(migrated_url, OWNER)
    code = {"code": totp.code_at(seed, time.time())}
    assert db_client.post(off, json=code, headers=owner).status_code == 204
    assert _login(db_client, OWNER)["access_token"]  # a password alone again
    assert db_client.post(off, json=code, headers=owner).status_code == 409
    logged = "SELECT count(*) FROM audit_log WHERE action = 'second_factor_disabled'"
    assert sql(migrated_url, logged) == 1


def test_a_support_session_cannot_turn_it_on_or_off(
    db_client: TestClient, migrated_url: str
) -> None:
    signup(db_client, email=OWNER)
    signup(db_client, email="staff@alterx.in", account="ALTERX")
    staff_session(migrated_url, "staff@alterx.in")
    support = support_session(migrated_url, OWNER)
    assert db_client.post("/auth/second-factor/setup", headers=support).status_code == 403
    disable = {"code": "123456"}
    response = db_client.post("/auth/second-factor/disable", json=disable, headers=support)
    assert response.status_code == 403


def test_staff_keep_the_sign_in_flow_and_cannot_turn_theirs_off(
    db_client: TestClient, migrated_url: str
) -> None:
    _make_staff(db_client, migrated_url)
    staff = staff_session(migrated_url, "staff@alterx.in")
    assert db_client.post("/auth/second-factor/setup", headers=staff).status_code == 409
    disable = {"code": "123456"}
    response = db_client.post("/auth/second-factor/disable", json=disable, headers=staff)
    assert response.status_code == 409


def test_staff_reset_an_owners_lost_second_factor_and_it_is_logged(
    db_client: TestClient, migrated_url: str
) -> None:
    owner = signup(db_client, email=OWNER)
    _turn_on(db_client, owner)
    signup(db_client, email="lead@alterx.in", account="ALTERX ops")
    lead = staff_session(migrated_url, "lead@alterx.in")
    lost = sql(migrated_url, "SELECT id FROM users WHERE email = :e", {"e": OWNER})

    reset = db_client.post(f"/admin/users/{lost}/second-factor/reset", headers=lead)
    assert reset.status_code == 204
    assert db_client.get("/accounts/me", headers=owner).status_code == 401  # signed out
    assert _login(db_client, OWNER)["access_token"]  # turned off: a password alone
    log = "SELECT actor_user_id FROM audit_log WHERE action = 'second_factor_reset'"
    assert sql(migrated_url, log + " AND target_id = :t", {"t": str(lost)}) == sql(
        migrated_url, "SELECT id FROM users WHERE email = 'lead@alterx.in'"
    )
    # Nothing left to reset.
    again = db_client.post(f"/admin/users/{lost}/second-factor/reset", headers=lead)
    assert again.status_code == 404
    assert _login(db_client, OWNER)["challenge"] is None
