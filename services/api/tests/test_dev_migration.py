"""Migration 0010 on a database that already has calls: they are not announced as news."""

import pytest

from .conftest import alembic, sql


def test_calls_that_ended_before_the_migration_are_never_announced(
    fresh_database: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    url: str = fresh_database()  # type: ignore[operator]
    alembic(url, monkeypatch, ("upgrade", "0009"))
    account = sql(url, "INSERT INTO accounts (name) VALUES ('a') RETURNING id")
    insert = (
        "INSERT INTO calls (account_id, status, direction, channel, ended_at)"
        " VALUES (:a, 'completed', 'outbound', 'instant', {ended}) RETURNING id"
    )
    ended = sql(url, insert.format(ended="now()"), {"a": account})
    open_call = sql(url, insert.format(ended="NULL"), {"a": account})

    alembic(url, monkeypatch, ("upgrade", "head"))
    query = "SELECT events_emitted_at IS NOT NULL FROM calls WHERE id = :c"
    assert sql(url, query, {"c": ended}) is True  # the past stays quiet
    assert sql(url, query, {"c": open_call}) is False  # a call still going will be announced
    assert sql(url, "SELECT voicemail FROM calls WHERE id = :c", {"c": ended}) is False
    alembic(url, monkeypatch, ("check",))  # the models and the migration agree

    alembic(url, monkeypatch, ("downgrade", "0009"))
    assert sql(url, "SELECT count(*) FROM calls") == 2  # going back keeps the calls
    alembic(url, monkeypatch, ("upgrade", "head"))
