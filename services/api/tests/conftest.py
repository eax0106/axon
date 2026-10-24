import asyncio
import os
import secrets
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.db import Base
from app.main import app
from app.providers.registry import VENDOR_KEYS
from app.settings import get_settings

ALL_KEYS = sorted(
    {key for vendors in VENDOR_KEYS.values() for keys in vendors.values() for key in keys}
)
ALEMBIC_INI = Path(__file__).parents[1] / "alembic.ini"
TEST_JWT_SECRET = "test-only-secret-" + "x" * 32


@pytest.fixture
def no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ALL_KEYS:
        monkeypatch.delenv(key, raising=False)
    for kind in VENDOR_KEYS:
        monkeypatch.delenv(f"AXON_{kind.upper()}_PROVIDER", raising=False)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, no_keys: None) -> Iterator[TestClient]:
    # Port 1 refuses connections, so readiness is measured against a dependency that is down.
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://axon:axon@127.0.0.1:1/axon")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    get_settings.cache_clear()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


# --- Real Postgres -------------------------------------------------------------------------
# AXON_TEST_DATABASE_URL points at a Postgres server whose user may create databases, e.g.
# postgresql+asyncpg://axon:axon@localhost:5432/postgres. Each test session gets its own database.


def sql(url: str, query: str, params: dict[str, Any] | None = None) -> Any:
    """Run one statement on `url` outside any transaction and return the first value."""

    async def run() -> Any:
        engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
        try:
            async with engine.connect() as conn:
                result = await conn.execute(text(query), params or {})
                return result.scalar() if result.returns_rows else None
        finally:
            await engine.dispose()

    return asyncio.run(run())


def alembic(url: str, monkeypatch: pytest.MonkeyPatch, *steps: tuple[str, ...]) -> None:
    """Run Alembic commands against `url`, e.g. ("upgrade", "head"), ("check",)."""
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    cfg = Config(str(ALEMBIC_INI))
    cfg.attributes["configure_logger"] = False
    for name, *args in steps:
        getattr(command, name)(cfg, *args)
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def server_url() -> str:
    url = os.environ.get("AXON_TEST_DATABASE_URL")
    if not url and os.environ.get("CI"):
        pytest.fail("AXON_TEST_DATABASE_URL must be set in CI; database tests may not skip there")
    if not url:
        pytest.skip("AXON_TEST_DATABASE_URL not set; database tests need a real Postgres")
    return url


@pytest.fixture(scope="session")
def fresh_database(server_url: str) -> Iterator[Any]:
    """Factory: create an empty database, return its URL; every one is dropped at session end."""
    made: list[str] = []

    def make() -> str:
        name = f"axon_test_{secrets.token_hex(4)}"
        sql(server_url, f'CREATE DATABASE "{name}"')
        made.append(name)
        return make_url(server_url).set(database=name).render_as_string(False)

    yield make
    for name in made:
        sql(server_url, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture(scope="session")
def migrated_url(fresh_database: Any) -> str:
    url: str = fresh_database()
    with pytest.MonkeyPatch.context() as mp:
        alembic(url, mp, ("upgrade", "head"))
    return url


@pytest.fixture
def db_client(
    migrated_url: str, monkeypatch: pytest.MonkeyPatch, no_keys: None
) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_URL", migrated_url)
    monkeypatch.setenv("AXON_JWT_SECRET", TEST_JWT_SECRET)
    get_settings.cache_clear()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()
    tables = ", ".join(f'"{t}"' for t in Base.metadata.tables)
    sql(migrated_url, f"TRUNCATE {tables} CASCADE")
