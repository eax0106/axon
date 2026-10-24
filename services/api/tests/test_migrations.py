from typing import Any

import pytest

from app.db import Base

from .conftest import alembic, sql

TABLES = (
    "SELECT string_agg(tablename, ',' ORDER BY tablename) FROM pg_tables"
    " WHERE schemaname = 'public'"
)
ENUM_TYPES = (
    "SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace"
    " WHERE n.nspname = 'public' AND t.typtype = 'e'"
)


def test_upgrade_downgrade_upgrade_on_an_empty_database_without_drift(
    fresh_database: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = fresh_database()
    assert sql(url, TABLES) is None

    alembic(url, monkeypatch, ("upgrade", "head"))
    assert sql(url, TABLES).split(",") == sorted([*Base.metadata.tables, "alembic_version"])
    alembic(url, monkeypatch, ("check",))  # raises if the models differ from the migrations

    alembic(url, monkeypatch, ("downgrade", "base"))
    assert sql(url, TABLES) == "alembic_version"
    assert sql(url, ENUM_TYPES) == 0

    alembic(url, monkeypatch, ("upgrade", "head"))
    assert len(sql(url, TABLES).split(",")) == len(Base.metadata.tables) + 1


def test_schema_constraints_hold_in_postgres(migrated_url: str) -> None:
    account = sql(migrated_url, "INSERT INTO accounts (name) VALUES ('a') RETURNING id")
    params = {"a": account}
    number = (
        "INSERT INTO numbers (account_id, provider, e164, number_type, status) "
        "VALUES (:a, 'vobiz', :e164, :t, 'active') RETURNING id"
    )
    assert sql(migrated_url, number, {**params, "e164": "+911400000001", "t": "140"})
    with pytest.raises(Exception, match="ck_numbers_number_type"):
        sql(migrated_url, number, {**params, "e164": "+911400000002", "t": "160"})
    # A released number keeps its row and can be bought again; a held one cannot be duplicated.
    sql(migrated_url, "UPDATE numbers SET status = 'released' WHERE e164 = '+911400000001'")
    assert sql(migrated_url, number, {**params, "e164": "+911400000001", "t": "140"})
    with pytest.raises(Exception, match="uq_numbers_e164_held"):
        sql(migrated_url, number, {**params, "e164": "+911400000001", "t": "140"})
    lead = "INSERT INTO leads (account_id, phone) VALUES (:a, '+919000000001')"
    sql(migrated_url, lead, params)
    with pytest.raises(Exception, match="uq_leads_account_id_phone"):
        sql(migrated_url, lead, params)
    sql(migrated_url, "DELETE FROM accounts WHERE id = :a", params)
    assert sql(migrated_url, "SELECT count(*) FROM leads") == 0  # account delete cascades
