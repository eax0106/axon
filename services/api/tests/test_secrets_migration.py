"""Migration 0015 on a database that already holds secrets in the clear: it encrypts every one,
and its downgrade gives them back as they were."""

import json
from typing import Any

import pytest

from app import secretbox

from .conftest import alembic, sql

ACTIONS = [
    {"kind": "http_api", "name": "crm", "auth": {"kind": "bearer", "secret": "action-key"}},
    {"kind": "http_api", "name": "open", "auth": {"kind": "none", "secret": ""}},
]
HOOK = {"url": "https://crm.example.in/h", "trigger": "all_connected", "secret": "hook-key"}
BUNDLE = json.dumps({"actions": ACTIONS, "result_webhook": HOOK, "script": "Namaste"})
# (query that reads the stored value, value written in the clear before the migration)
STORED = [
    ("SELECT secret FROM lead_connections", "intake-secret"),
    ("SELECT meta_page_token FROM lead_connections", "meta-token"),
    ("SELECT google_refresh_token FROM lead_connections", "sheets-token"),
    ("SELECT refresh_token FROM google_connections", "calendar-token"),
    ("SELECT secret FROM webhook_endpoints", "whsec_endpoint"),
    ("SELECT target_secret FROM webhook_deliveries", "delivery-secret"),
    ("SELECT draft->'actions'->0->'auth'->>'secret' FROM employees", "action-key"),
    ("SELECT draft->'result_webhook'->>'secret' FROM employees", "hook-key"),
    ("SELECT bundle->'actions'->0->'auth'->>'secret' FROM employee_versions", "action-key"),
    ("SELECT bundle->'result_webhook'->>'secret' FROM employee_versions", "hook-key"),
]


def _seed_plain(url: str) -> None:
    account = sql(url, "INSERT INTO accounts (name) VALUES ('a') RETURNING id")
    employee = sql(
        url,
        "INSERT INTO employees (account_id, name, channel, purpose, status, language, draft)"
        " VALUES (:a, 'Asha', 'instant', 'service', 'draft', 'te', CAST(:b AS jsonb)) RETURNING id",
        {"a": account, "b": BUNDLE},
    )
    sql(
        url,
        "INSERT INTO employee_versions (employee_id, version, bundle)"
        " VALUES (:e, 1, CAST(:b AS jsonb))",
        {"e": employee, "b": BUNDLE},
    )
    sql(
        url,
        "INSERT INTO lead_connections (account_id, employee_id, secret, meta_page_token,"
        " google_refresh_token) VALUES (:a, :e, 'intake-secret', 'meta-token', 'sheets-token')",
        {"a": account, "e": employee},
    )
    sql(
        url,
        "INSERT INTO google_connections (account_id, refresh_token) VALUES (:a, 'calendar-token')",
        {"a": account},
    )
    sql(
        url,
        "INSERT INTO webhook_endpoints (account_id, url, secret, events)"
        " VALUES (:a, 'https://x.example.in', 'whsec_endpoint', '{call.completed}')",
        {"a": account},
    )
    event = sql(
        url,
        "INSERT INTO webhook_events (account_id, type, data) VALUES (:a, 'call.completed', '{}')"
        " RETURNING id",
        {"a": account},
    )
    sql(
        url,
        "INSERT INTO webhook_deliveries (account_id, event_id, target_url, target_secret, event,"
        " payload, status) VALUES (:a, :v, 'https://y.example.in', 'delivery-secret',"
        " 'call.completed', '{}', 'pending')",
        {"a": account, "v": event},
    )


def test_existing_secrets_are_encrypted_and_the_downgrade_restores_them(
    fresh_database: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    url: str = fresh_database()
    alembic(url, monkeypatch, ("upgrade", "0014"))
    _seed_plain(url)

    alembic(url, monkeypatch, ("upgrade", "head"))
    for query, plain in STORED:
        stored = sql(url, query)
        assert stored != plain, query
        assert secretbox.unseal(stored) == plain, query
    assert sql(url, "SELECT draft->'actions'->1->'auth'->>'secret' FROM employees") == ""  # empty
    assert sql(url, "SELECT draft->>'script' FROM employees") == "Namaste"  # the rest untouched
    alembic(url, monkeypatch, ("check",))  # the models and the migration agree

    alembic(url, monkeypatch, ("downgrade", "0014"))
    for query, plain in STORED:
        assert sql(url, query) == plain, query
    widths = "SELECT character_maximum_length FROM information_schema.columns WHERE column_name = :c AND table_name = :t"  # noqa: E501
    assert sql(url, widths, {"t": "lead_connections", "c": "secret"}) == 64
    alembic(url, monkeypatch, ("upgrade", "head"))


def test_the_migration_refuses_to_run_without_the_key_when_there_are_secrets(
    fresh_database: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    url: str = fresh_database()
    alembic(url, monkeypatch, ("upgrade", "0014"))
    _seed_plain(url)
    monkeypatch.delenv(secretbox.KEY_ENV)
    with pytest.raises(secretbox.SecretsNotConfiguredError, match="AXON_SECRETS_KEY"):
        alembic(url, monkeypatch, ("upgrade", "head"))
    assert sql(url, "SELECT secret FROM lead_connections") == "intake-secret"  # nothing half-done
