"""Stored secrets are encrypted under AXON_SECRETS_KEY (B14 security review F5)."""

# ruff: noqa: S106 - every secret here is a made-up test value

import asyncio
from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import Text, select, type_coerce

from app import secretbox
from app.main import app
from app.models import (
    Account,
    Channel,
    Employee,
    EmployeeVersion,
    GoogleConnection,
    LeadConnection,
    Purpose,
    User,
    WebhookDelivery,
    WebhookEndpoint,
    WebhookEvent,
)
from app.secretrotate import encrypted_columns, rotate_all

from .conftest import alembic, sql
from .helpers import run_db

OLD, NEW = Fernet.generate_key().decode(), Fernet.generate_key().decode()
# Every secret the schema holds, each with a value that is easy to spot in raw storage.
EXPECTED_COLUMNS = {
    "users": {"totp_secret"},
    "employees": {"draft"},
    "employee_versions": {"bundle"},
    "lead_connections": {"secret", "meta_page_token", "google_refresh_token"},
    "google_connections": {"refresh_token"},
    "webhook_endpoints": {"secret"},
    "webhook_deliveries": {"target_secret"},
}


def bundle(tag: str) -> dict[str, Any]:
    return {
        "actions": [
            {
                "kind": "http_api",
                "name": "crm",
                "auth": {"kind": "bearer", "secret": f"{tag}-action"},
            },
            {"kind": "http_api", "name": "open", "auth": {"kind": "none", "secret": ""}},
            {"kind": "transfer", "name": "desk"},
        ],
        "result_webhook": {"url": "https://crm.example.in/hook", "secret": f"{tag}-hook"},
        "script": "Namaste",
    }


async def _store(factory: Any) -> None:
    async with factory() as session:
        account = Account(name="Acme")
        session.add(account)
        await session.flush()
        employee = Employee(
            account_id=account.id, name="Asha", channel=Channel.INSTANT,
            purpose=Purpose.SERVICE, language="te", draft=bundle("draft"),
        )  # fmt: skip
        session.add(employee)
        session.add(
            User(
                account_id=account.id,
                email="s@alterx.in",
                password_hash="x",
                totp_secret="SEEDSEEDSEED",
            )
        )
        await session.flush()
        session.add(EmployeeVersion(employee_id=employee.id, version=1, bundle=bundle("live")))
        session.add(
            LeadConnection(
                account_id=account.id, employee_id=employee.id, secret="intake-secret",
                meta_page_token="meta-token", google_refresh_token="sheets-token",
            )
        )  # fmt: skip
        session.add(GoogleConnection(account_id=account.id, refresh_token="calendar-token"))
        endpoint = WebhookEndpoint(
            account_id=account.id,
            url="https://x.example.in",
            secret="whsec_endpoint",
            events=["call.completed"],
        )
        event = WebhookEvent(account_id=account.id, type="call.completed", data={})
        session.add_all([endpoint, event])
        await session.flush()
        session.add(
            WebhookDelivery(
                account_id=account.id, event_id=event.id, target_url="https://y.example.in",
                target_secret="delivery-secret", event="call.completed", payload={},
            )
        )  # fmt: skip
        await session.commit()


PLAIN = [
    "SEEDSEEDSEED", "draft-action", "draft-hook", "live-action", "live-hook", "intake-secret",
    "meta-token", "sheets-token", "calendar-token", "whsec_endpoint", "delivery-secret",
]  # fmt: skip


async def _raw_dump(factory: Any) -> str:
    """Every encrypted column as stored, as one string."""
    out: list[str] = []
    async with factory() as session:
        for columns in encrypted_columns().values():
            for column in columns:
                rows = await session.execute(select(type_coerce(column, Text)))
                out.extend(str(v) for (v,) in rows)
    return "\n".join(out)


async def _read_back(factory: Any) -> list[str]:
    async with factory() as session:
        employee = await session.scalar(select(Employee))
        version = await session.scalar(select(EmployeeVersion))
        user = await session.scalar(select(User))
        lead = await session.scalar(select(LeadConnection))
        google = await session.scalar(select(GoogleConnection))
        endpoint = await session.scalar(select(WebhookEndpoint))
        delivery = await session.scalar(select(WebhookDelivery))
        assert employee and version and user and lead and google and endpoint and delivery
        return [
            str(user.totp_secret),
            employee.draft["actions"][0]["auth"]["secret"],
            employee.draft["result_webhook"]["secret"],
            version.bundle["actions"][0]["auth"]["secret"],
            version.bundle["result_webhook"]["secret"],
            lead.secret, str(lead.meta_page_token), str(lead.google_refresh_token),
            google.refresh_token, endpoint.secret, str(delivery.target_secret),
        ]  # fmt: skip


@pytest.fixture
def stored(fresh_database: Any, monkeypatch: pytest.MonkeyPatch) -> str:
    url: str = fresh_database()
    alembic(url, monkeypatch, ("upgrade", "head"))
    monkeypatch.setenv(secretbox.KEY_ENV, OLD)
    run_db(url, _store)
    return url


def test_every_secret_column_is_known_to_the_encryption() -> None:
    found = {t.name: {c.name for c in cols} for t, cols in encrypted_columns().items()}
    assert found == EXPECTED_COLUMNS


def test_no_secret_is_readable_in_the_database_and_the_app_reads_every_one(stored: str) -> None:
    raw = run_db(stored, _raw_dump)
    for value in PLAIN:
        assert value not in raw
    assert run_db(stored, _read_back) == PLAIN
    # What is not secret stays plain JSON that SQL can read.
    assert sql(stored, "SELECT draft->>'script' FROM employees") == "Namaste"
    assert sql(stored, "SELECT draft->'actions'->1->'auth'->>'secret' FROM employees") == ""


def test_a_read_with_the_wrong_key_fails_loudly_and_says_why(
    stored: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(secretbox.KEY_ENV, NEW)
    with pytest.raises(secretbox.SecretsNotConfiguredError, match="was a key dropped too soon"):
        run_db(stored, _read_back)


def test_rotation_moves_every_secret_to_the_new_key(
    stored: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(secretbox.KEY_ENV, f"{NEW},{OLD}")  # the new key first; the old still reads
    assert run_db(stored, _read_back) == PLAIN
    counts = asyncio.run(rotate_all(stored))
    assert counts == {
        "users": 1, "employees": 1, "employee_versions": 1, "lead_connections": 1,
        "google_connections": 1, "webhook_endpoints": 1, "webhook_deliveries": 1,
    }  # fmt: skip
    monkeypatch.setenv(secretbox.KEY_ENV, NEW)  # the old key dropped
    assert run_db(stored, _read_back) == PLAIN


def test_a_missing_or_broken_key_stops_the_api_at_startup_and_says_what_to_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for value in ("", " , ", "not-a-fernet-key"):
        monkeypatch.setenv(secretbox.KEY_ENV, value)
        with (
            pytest.raises(secretbox.SecretsNotConfiguredError, match="AXON_SECRETS_KEY"),
            TestClient(app),
        ):
            pass
    monkeypatch.delenv(secretbox.KEY_ENV)
    with pytest.raises(secretbox.SecretsNotConfiguredError, match=r"app\.secretbox new-key"):
        secretbox.check()


def test_the_worker_refuses_to_start_without_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from worker.main import startup

    monkeypatch.delenv(secretbox.KEY_ENV)
    with pytest.raises(secretbox.SecretsNotConfiguredError):
        asyncio.run(startup({}))


def test_a_value_is_sealed_differently_each_time_and_opens_with_any_listed_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(secretbox.KEY_ENV, OLD)
    first, second = secretbox.seal("s3cret"), secretbox.seal("s3cret")
    assert first != second and "s3cret" not in first
    monkeypatch.setenv(secretbox.KEY_ENV, f"{NEW},{OLD}")
    assert secretbox.unseal(first) == "s3cret"
    moved = secretbox.reseal(first)
    monkeypatch.setenv(secretbox.KEY_ENV, NEW)
    assert secretbox.unseal(moved) == "s3cret"


def test_the_cli_makes_a_key_that_works(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    assert secretbox.main(["new-key"]) == 0
    monkeypatch.setenv(secretbox.KEY_ENV, capsys.readouterr().out.strip())
    secretbox.check()
    assert secretbox.main(["nonsense"]) == 2
