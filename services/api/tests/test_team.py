"""Owners invite members by email, see and remove them; anyone can reset a forgotten password."""

import json
import re
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.account import team
from app.providers.email.resend import ResendEmail

from .conftest import sql
from .helpers import PASSWORD, signup, support_session

APP = "https://app.example.in"


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """The email provider, recording what it is asked to send."""
    mails: list[dict[str, Any]] = []

    def resend(request: httpx.Request) -> httpx.Response:
        mails.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "email-1"})

    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("EMAIL_FROM", "team@example.in")
    monkeypatch.setenv("AXON_APP_PUBLIC_URL", APP)
    monkeypatch.setattr(
        team, "require", lambda _kind: ResendEmail(transport=httpx.MockTransport(resend))
    )
    return mails


def _token(mail: dict[str, Any], path: str) -> str:
    found = re.search(rf"{APP}/{path}#(\S+)", mail["text"])
    assert found, mail["text"]
    return found.group(1)


def _invite(client: TestClient, owner: dict[str, str], email: str) -> Any:
    return client.post("/team/invites", json={"email": email}, headers=owner)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_an_invited_colleague_joins_as_a_member_who_cannot_reach_owner_pages(
    db_client: TestClient, migrated_url: str, sent: list[dict[str, Any]]
) -> None:
    owner = signup(db_client, email="owner@acme.in")
    invited = _invite(db_client, owner, " Ravi@Acme.in ")
    assert invited.status_code == 201, invited.text
    assert invited.json()["email"] == "ravi@acme.in"
    (mail,) = sent
    assert mail["to"] == ["ravi@acme.in"] and "Join Acme on Axon" == mail["subject"]
    token = _token(mail, "join")
    # Only a hash is kept.
    assert (
        sql(migrated_url, "SELECT count(*) FROM email_tokens WHERE token_hash = :t", {"t": token})
        == 0
    )

    info = db_client.post("/auth/invites/check", json={"token": token})
    assert info.json() == {"email": "ravi@acme.in", "account_name": "Acme"}
    joined = db_client.post("/auth/invites/accept", json={"token": token, "password": "a-new-pass"})
    assert joined.status_code == 201, joined.text
    member = _bearer(joined.json()["access_token"])
    me = db_client.get("/accounts/me", headers=member).json()
    assert me["user"]["role"] == "member"
    assert (
        me["account"]["id"] == db_client.get("/accounts/me", headers=owner).json()["account"]["id"]
    )
    assert db_client.get("/calls", headers=member).status_code == 200
    assert db_client.get("/leads", headers=member).status_code == 200
    assert db_client.get("/team", headers=member).status_code == 403
    for path, body in (
        ("/developer/keys", {"name": "mine"}),
        ("/wallet/topup/order", {"amount": "500"}),
        ("/numbers/purchase", {}),
    ):
        assert db_client.post(path, json=body, headers=member).status_code == 403, path
    settings = {"name": "Mine", "max_call_s": 600}
    assert db_client.put("/account/settings", json=settings, headers=member).status_code == 403
    # The member signs in with the password chosen.
    login = db_client.post("/auth/login", json={"email": "ravi@acme.in", "password": "a-new-pass"})
    assert login.json()["access_token"]
    actions = sql(migrated_url, "SELECT string_agg(action, ',' ORDER BY id) FROM audit_log")
    assert "invite_sent" in actions and "invite_accepted" in actions


def test_a_used_revoked_or_expired_link_is_refused(
    db_client: TestClient, migrated_url: str, sent: list[dict[str, Any]]
) -> None:
    owner = signup(db_client, email="owner@acme.in")
    _invite(db_client, owner, "a@acme.in")
    used = _token(sent[-1], "join")
    accept = {"token": used, "password": "a-new-pass"}
    assert db_client.post("/auth/invites/accept", json=accept).status_code == 201
    assert db_client.post("/auth/invites/accept", json=accept).status_code == 410

    revoked_id = _invite(db_client, owner, "b@acme.in").json()["id"]
    revoked = _token(sent[-1], "join")
    assert db_client.delete(f"/team/invites/{revoked_id}", headers=owner).status_code == 204
    gone = db_client.post("/auth/invites/check", json={"token": revoked})
    assert gone.status_code == 410

    _invite(db_client, owner, "c@acme.in")
    old = _token(sent[-1], "join")
    _invite(db_client, owner, "c@acme.in")  # sending again cancels the earlier link
    assert db_client.post("/auth/invites/check", json={"token": old}).status_code == 410
    expired = _token(sent[-1], "join")
    sql(migrated_url, "UPDATE email_tokens SET expires_at = now() - interval '1 second'")
    assert db_client.post("/auth/invites/check", json={"token": expired}).status_code == 410
    assert db_client.post("/auth/invites/check", json={"token": "x" * 43}).status_code == 410


def test_the_owner_lists_and_removes_members_and_a_removed_session_stops_at_once(
    db_client: TestClient, migrated_url: str, sent: list[dict[str, Any]]
) -> None:
    owner = signup(db_client, email="owner@acme.in")
    _invite(db_client, owner, "ravi@acme.in")
    token = _token(sent[-1], "join")
    member = _bearer(
        db_client.post(
            "/auth/invites/accept", json={"token": token, "password": "a-new-pass"}
        ).json()["access_token"]
    )
    _invite(db_client, owner, "later@acme.in")

    listed = db_client.get("/team", headers=owner).json()
    assert [(m["email"], m["role"]) for m in listed["members"]] == [
        ("owner@acme.in", "owner"),
        ("ravi@acme.in", "member"),
    ]
    assert [i["email"] for i in listed["invites"]] == ["later@acme.in"]
    owner_id, member_id = (m["id"] for m in listed["members"])
    assert db_client.delete(f"/team/members/{owner_id}", headers=owner).status_code == 409
    assert db_client.delete(f"/team/members/{member_id}", headers=member).status_code == 403

    assert db_client.delete(f"/team/members/{member_id}", headers=owner).status_code == 204
    assert db_client.get("/calls", headers=member).status_code == 401
    removed = "SELECT count(*) FROM audit_log WHERE action = 'member_removed'"
    assert sql(migrated_url, removed) == 1
    # Another account's owner cannot touch this account's people or invites.
    stranger = signup(db_client, email="other@else.in", account="Else")
    assert db_client.delete(f"/team/members/{owner_id}", headers=stranger).status_code == 404
    invite_id = listed["invites"][0]["id"]
    assert db_client.delete(f"/team/invites/{invite_id}", headers=stranger).status_code == 404


def test_an_email_that_already_signs_in_cannot_be_invited(
    db_client: TestClient, sent: list[dict[str, Any]]
) -> None:
    owner = signup(db_client, email="owner@acme.in")
    signup(db_client, email="taken@else.in", account="Else")
    assert _invite(db_client, owner, "TAKEN@else.in").status_code == 409
    assert sent == []


def test_invites_are_not_sent_from_a_support_session(
    db_client: TestClient, migrated_url: str, sent: list[dict[str, Any]]
) -> None:
    signup(db_client, email="owner@acme.in")
    signup(db_client, email="staff@alterx.in", account="ALTERX")
    sql(migrated_url, "UPDATE users SET is_platform_admin = true WHERE email = 'staff@alterx.in'")
    support = support_session(migrated_url, "owner@acme.in")
    assert _invite(db_client, support, "x@acme.in").status_code == 403


def test_without_the_email_provider_nothing_is_stored_and_the_answer_is_503(
    db_client: TestClient, migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    owner = signup(db_client, email="owner@acme.in")
    answer = _invite(db_client, owner, "x@acme.in")
    assert answer.status_code == 503 and answer.json()["error"] == "provider_not_configured"
    reset = db_client.post("/auth/password-reset", json={"email": "owner@acme.in"})
    assert reset.status_code == 503
    assert sql(migrated_url, "SELECT count(*) FROM email_tokens") == 0


def test_a_password_reset_link_sets_a_new_password_once_and_signs_out_everywhere(
    db_client: TestClient, migrated_url: str, sent: list[dict[str, Any]]
) -> None:
    owner = signup(db_client, email="owner@acme.in")
    asked = db_client.post("/auth/password-reset", json={"email": "Owner@acme.in"})
    unknown = db_client.post("/auth/password-reset", json={"email": "nobody@acme.in"})
    assert asked.status_code == unknown.status_code == 202 and asked.json() == unknown.json()
    (mail,) = sent  # only a real sign-in gets an email
    token = _token(mail, "reset-password")
    db_client.post("/auth/password-reset", json={"email": "owner@acme.in"})
    other = _token(sent[-1], "reset-password")

    done = db_client.post(
        "/auth/password-reset/confirm", json={"token": token, "password": "brand-new-pass"}
    )
    assert done.status_code == 204
    assert db_client.get("/accounts/me", headers=owner).status_code == 401  # signed out
    old = db_client.post("/auth/login", json={"email": "owner@acme.in", "password": PASSWORD})
    assert old.status_code == 401
    new = db_client.post(
        "/auth/login", json={"email": "owner@acme.in", "password": "brand-new-pass"}
    )
    assert new.json()["access_token"]
    for again in (token, other):  # used, and every other reset link stops with it
        answer = db_client.post(
            "/auth/password-reset/confirm", json={"token": again, "password": "third-pass-1"}
        )
        assert answer.status_code == 410
    actions = "SELECT count(*) FROM audit_log WHERE action = 'password_reset'"
    assert sql(migrated_url, actions) == 1


def test_a_reset_link_expires_after_an_hour(
    db_client: TestClient, migrated_url: str, sent: list[dict[str, Any]]
) -> None:
    signup(db_client, email="owner@acme.in")
    db_client.post("/auth/password-reset", json={"email": "owner@acme.in"})
    token = _token(sent[-1], "reset-password")
    hours = sql(
        migrated_url, "SELECT extract(epoch FROM expires_at - created_at) / 3600 FROM email_tokens"
    )
    assert round(float(hours)) == 1
    sql(migrated_url, "UPDATE email_tokens SET expires_at = now() - interval '1 second'")
    answer = db_client.post(
        "/auth/password-reset/confirm", json={"token": token, "password": "brand-new-pass"}
    )
    assert answer.status_code == 410
