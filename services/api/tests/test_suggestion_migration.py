"""Migration 0014 on a database that already has teaching suggestions: each gets the key a new
struggle is compared with, so a quote the owner already saw is still not shown again."""

import pytest

from app.training.struggle import quote_key

from .conftest import alembic, sql

QUOTES = ("Do you deliver to KUKATPALLY?", "  क्या आप  रविवार को खुले हैं?! ", "ఫీజు ఎంత?")


def test_existing_suggestions_get_the_same_key_new_ones_would(
    fresh_database: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    url: str = fresh_database()  # type: ignore[operator]
    alembic(url, monkeypatch, ("upgrade", "0013"))
    account = sql(url, "INSERT INTO accounts (name) VALUES ('a') RETURNING id")
    employee = sql(
        url,
        "INSERT INTO employees (account_id, name, channel, purpose, status, language)"
        " VALUES (:a, 'Asha', 'inbound', 'service', 'live', 'en') RETURNING id",
        {"a": account},
    )
    for quote in QUOTES:
        sql(
            url,
            "INSERT INTO training_suggestions (account_id, employee_id, kind, reason,"
            " caller_quote, status) VALUES (:a, :e, 'fact', 'unanswered', :q, 'dismissed')",
            {"a": account, "e": employee, "q": quote},
        )

    alembic(url, monkeypatch, ("upgrade", "head"))
    for quote in QUOTES:
        stored = sql(
            url, "SELECT quote_key FROM training_suggestions WHERE caller_quote = :q", {"q": quote}
        )
        assert stored == quote_key(quote) and stored, quote
    alembic(url, monkeypatch, ("check",))  # the models and the migration agree

    alembic(url, monkeypatch, ("downgrade", "0013"))
    assert sql(url, "SELECT count(*) FROM training_suggestions") == 3  # going back keeps them
    alembic(url, monkeypatch, ("upgrade", "head"))
