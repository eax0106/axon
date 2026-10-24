import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from fastapi.testclient import TestClient

from app.auth import TOKEN_TTL, issue_token
from app.models import User
from app.settings import get_settings

from .conftest import TEST_JWT_SECRET, sql

EMAIL, PASSWORD = "Owner@Example.com", "correct horse battery"


def _signup(client: TestClient, email: str = EMAIL) -> str:
    body = {"email": email, "password": PASSWORD, "account_name": "Acme Realty"}
    response = client.post("/auth/signup", json=body)
    assert response.status_code == 201, response.text
    token: str = response.json()["access_token"]
    return token


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_signup_creates_owner_and_account_and_returns_a_working_token(
    db_client: TestClient,
) -> None:
    me = db_client.get("/accounts/me", headers=_auth(_signup(db_client))).json()
    assert me["user"]["email"] == "owner@example.com"
    assert me["user"]["role"] == "owner"
    assert me["account"]["name"] == "Acme Realty"


def test_password_is_stored_as_an_argon2id_hash(db_client: TestClient, migrated_url: str) -> None:
    _signup(db_client)
    stored = sql(migrated_url, "SELECT password_hash FROM users")
    assert stored.startswith("$argon2id$")
    assert PASSWORD not in stored


def test_email_is_unique_regardless_of_case(db_client: TestClient) -> None:
    _signup(db_client)
    body = {"email": "OWNER@example.com", "password": PASSWORD, "account_name": "Other"}
    assert db_client.post("/auth/signup", json=body).status_code == 409


def test_login_accepts_the_right_password_only(db_client: TestClient) -> None:
    _signup(db_client)
    ok = db_client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert ok.status_code == 200
    assert (
        db_client.get("/accounts/me", headers=_auth(ok.json()["access_token"])).status_code == 200
    )
    wrong = db_client.post("/auth/login", json={"email": EMAIL, "password": "wrong password"})
    unknown = db_client.post("/auth/login", json={"email": "no@one.in", "password": PASSWORD})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": "invalid email or password"}


@pytest.mark.parametrize(
    "body",
    [
        {"email": "not-an-email", "password": PASSWORD, "account_name": "A"},
        {"email": EMAIL, "password": "short", "account_name": "A"},
        {"email": EMAIL, "password": PASSWORD, "account_name": ""},
    ],
)
def test_signup_rejects_bad_input(db_client: TestClient, body: dict[str, str]) -> None:
    assert db_client.post("/auth/signup", json=body).status_code == 422


def _user(migrated_url: str) -> User:
    return User(id=uuid.UUID(sql(migrated_url, "SELECT id::text FROM users LIMIT 1")))


def test_expired_tampered_and_foreign_tokens_are_rejected(
    db_client: TestClient, migrated_url: str
) -> None:
    token = _signup(db_client)
    user = _user(migrated_url)
    expired = issue_token(user, now=datetime.now(UTC) - TOKEN_TTL - timedelta(seconds=1))
    foreign = jwt.encode(
        {"sub": str(user.id), "iat": datetime.now(UTC), "exp": datetime.now(UTC) + TOKEN_TTL},
        "another-secret-" + "y" * 32,
        algorithm="HS256",
    )
    unsigned = jwt.encode({"sub": str(user.id)}, key="", algorithm="none")
    head, payload, sig = token.split(".")
    tampered = f"{head}.{payload}.{sig[::-1]}"
    for bad in (expired, foreign, unsigned, tampered, "garbage"):
        response = db_client.get("/accounts/me", headers=_auth(bad))
        assert response.status_code == 401, bad
    assert db_client.get("/accounts/me").status_code == 401


def test_token_for_a_deleted_user_is_rejected(db_client: TestClient, migrated_url: str) -> None:
    token = _signup(db_client)
    sql(migrated_url, "DELETE FROM users")
    assert db_client.get("/accounts/me", headers=_auth(token)).status_code == 401


@pytest.mark.parametrize(("role", "expected"), [("owner", 403), ("member", 403), ("admin", 200)])
def test_admin_providers_needs_the_admin_role(
    db_client: TestClient, migrated_url: str, role: str, expected: int
) -> None:
    token = _signup(db_client)
    sql(migrated_url, "UPDATE users SET role = :r", {"r": role})
    assert db_client.get("/admin/providers", headers=_auth(token)).status_code == expected


def test_admin_providers_needs_a_token(db_client: TestClient) -> None:
    assert db_client.get("/admin/providers").status_code == 401


def test_missing_jwt_secret_answers_503_and_creates_nothing(
    db_client: TestClient, migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AXON_JWT_SECRET", "")
    get_settings.cache_clear()
    body: dict[str, Any] = {"email": EMAIL, "password": PASSWORD, "account_name": "A"}
    response = db_client.post("/auth/signup", json=body)
    assert response.status_code == 503
    assert response.json()["error"] == "auth_not_configured"
    assert response.json()["missing_keys"] == ["AXON_JWT_SECRET"]
    assert sql(migrated_url, "SELECT count(*) FROM accounts") == 0
    monkeypatch.setenv("AXON_JWT_SECRET", TEST_JWT_SECRET)
    get_settings.cache_clear()
