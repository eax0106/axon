"""Test helpers for the account-scoped API: sign up, add a member, seed the voice catalog."""

import asyncio
import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth import issue_token
from app.models import User
from app.voices import seed_voices

from .conftest import sql

PASSWORD = "correct horse battery"  # noqa: S105 - test credential


def seed(url: str) -> None:
    async def run() -> None:
        engine = create_async_engine(url)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as session:
                await seed_voices(session)
        finally:
            await engine.dispose()

    asyncio.run(run())


def signup(
    client: TestClient, email: str = "owner@example.com", account: str = "Acme"
) -> dict[str, str]:
    body = {"email": email, "password": PASSWORD, "account_name": account}
    response = client.post("/auth/signup", json=body)
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def account_id(client: TestClient, headers: dict[str, str]) -> str:
    me: dict[str, Any] = client.get("/accounts/me", headers=headers).json()
    return str(me["account"]["id"])


def add_member(
    client: TestClient, url: str, owner: dict[str, str], email: str = "member@example.com"
) -> dict[str, str]:
    """A second user with role `member` in the owner's account."""
    user_id = uuid.uuid4()
    sql(
        url,
        "INSERT INTO users (id, account_id, email, password_hash, role)"
        " VALUES (:i, :a, :e, 'x', 'member')",
        {"i": user_id, "a": uuid.UUID(account_id(client, owner)), "e": email},
    )
    return {"Authorization": f"Bearer {issue_token(User(id=user_id))}"}
