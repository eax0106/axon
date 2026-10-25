"""Test helpers for the account-scoped API: sign up, add a member, seed the voice catalog."""

import asyncio
import json
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


def live_employee(
    client: TestClient,
    url: str,
    owner: dict[str, str],
    *,
    variables: tuple[str, ...] = (),
    channel: str = "instant",
    number: str = "+911400000001",
    live: bool = True,
) -> str:
    """An employee that is published and live with a number attached (for dialer tests)."""
    created = client.post("/employees", json={"channel": channel, "name": "Asha"}, headers=owner)
    employee = str(created.json()["id"])
    script = {"welcome_message": "Hi {{name}}", "pre_call_variables": list(variables)}
    client.put(f"/employees/{employee}/script", json=script, headers=owner)
    client.post(f"/employees/{employee}/publish", headers=owner)
    account = sql(url, "SELECT account_id FROM employees WHERE id = :e", {"e": employee})
    number_id = sql(
        url,
        "INSERT INTO numbers (account_id, provider, e164, number_type, status)"
        " VALUES (:a, 'vobiz', :n, 'regular', 'active') RETURNING id",
        {"a": account, "n": number},
    )
    sql(url, "UPDATE employees SET number_id = :n WHERE id = :e", {"n": number_id, "e": employee})
    if live:
        assert client.post(f"/employees/{employee}/activate", headers=owner).status_code == 200
    return employee


def run_db(url: str, work: Any) -> Any:
    """Run `await work(session_factory)` against the test database on a fresh event loop."""

    async def go() -> Any:
        engine = create_async_engine(url)
        try:
            return await work(async_sessionmaker(engine, expire_on_commit=False))
        finally:
            await engine.dispose()

    return asyncio.run(go())


CALL_COLUMNS = {
    "status", "direction", "channel", "outcome", "sentiment", "summary", "duration_s",
    "credits_charged", "created_at", "started_at", "answered_at", "ended_at", "is_test",
    "transcript", "captured", "recording_key", "analysis_status", "campaign_id", "attempt",
}  # fmt: skip


def add_lead(url: str, account: Any, phone: str, name: str | None = None, **fields: Any) -> Any:
    return sql(
        url,
        "INSERT INTO leads (account_id, phone, name, fields) VALUES (:a, :p, :n, CAST(:f AS jsonb))"
        " RETURNING id",
        {"a": account, "p": phone, "n": name, "f": json.dumps(fields)},
    )


def add_call(url: str, account: Any, employee: Any = None, lead: Any = None, **cols: Any) -> Any:
    """Insert a call row with the columns given (defaults: a completed outbound instant call)."""
    unknown = set(cols) - CALL_COLUMNS
    assert not unknown, unknown
    values: dict[str, Any] = {"status": "completed", "direction": "outbound", "channel": "instant"}
    values.update(cols)
    for key in ("transcript", "captured"):
        if key in values:
            values[key] = json.dumps(values[key])
    names = ["account_id", "employee_id", "lead_id", *values]
    marks = [
        ":account_id",
        ":employee_id",
        ":lead_id",
        *[f"CAST(:{k} AS jsonb)" if k in ("transcript", "captured") else f":{k}" for k in values],
    ]
    return sql(
        url,
        f"INSERT INTO calls ({', '.join(names)}) VALUES ({', '.join(marks)}) RETURNING id",  # noqa: S608
        {"account_id": account, "employee_id": employee, "lead_id": lead, **values},
    )
