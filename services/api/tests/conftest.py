import asyncio
import importlib.util
import os
import secrets
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.db import Base
from app.main import app
from app.providers.kyc.vobiz import VobizKyc
from app.providers.registry import VENDOR_KEYS
from app.providers.speech import common
from app.providers.telephony.vobiz import BASE_URL, VobizTelephony
from app.settings import get_settings

from .knowledge_vendor import Vendor
from .vobiz_fake import VobizAccount

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


def reseed_dial_rules(url: str) -> None:
    """Put the launch rule table back (migration 0005 seeds it; a TRUNCATE empties it)."""
    path = ALEMBIC_INI.parent / "migrations" / "versions" / "0005_billing_and_numbers.py"
    spec = importlib.util.spec_from_file_location("migration_0005", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = module.default_rules()
    marks = ", ".join(f"(:p{i}, :n{i}, :c{i}, :a{i}, :r{i})" for i in range(len(rows)))
    params = {
        f"{key}{i}": row[name]
        for i, row in enumerate(rows)
        for key, name in (
            ("p", "purpose"),
            ("n", "number_type"),
            ("c", "context"),
            ("a", "allowed"),
            ("r", "reason"),
        )
    }
    sql(
        url,
        f"INSERT INTO dial_rules (purpose, number_type, context, allowed, reason) VALUES {marks}",  # noqa: S608
        params,
    )


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
    reseed_dial_rules(migrated_url)


@pytest.fixture
def vobiz(monkeypatch: pytest.MonkeyPatch) -> Iterator[VobizAccount]:
    """Vobiz's number store and KYC with keys set; every adapter talks to this fake account."""
    monkeypatch.setenv("VOBIZ_AUTH_ID", "MA_TEST")
    monkeypatch.setenv("VOBIZ_AUTH_TOKEN", "token")
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")  # the speech legs: no call starts without them
    fake = VobizAccount()
    transport = httpx.MockTransport(fake.handler)

    def client(self: Any, suffix: str = "") -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=f"{BASE_URL}/Account/MA_TEST{suffix}",
            headers=self._headers,
            transport=transport,
        )

    monkeypatch.setattr(VobizTelephony, "_client", lambda self: client(self))
    monkeypatch.setattr(VobizKyc, "_client", lambda self: client(self, "/kyc"))
    yield fake


# --- Campaign tests: a started API with the public URLs set, and the carrier behind it ------------


@pytest.fixture
def api(db_client: TestClient, migrated_url: str, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from .helpers import seed

    seed(migrated_url)
    monkeypatch.setenv("AXON_ENGINE_PUBLIC_URL", "https://engine.example.in")
    monkeypatch.setenv("AXON_API_PUBLIC_URL", "https://api.example.in")
    return db_client


@pytest.fixture
def carrier(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Any, VobizTelephony]]:
    from .dialing import Carrier

    monkeypatch.setenv("VOBIZ_AUTH_ID", "MA_TEST")
    monkeypatch.setenv("VOBIZ_AUTH_TOKEN", "token")
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")  # the speech legs: no call starts without them
    fake = Carrier()
    yield fake, VobizTelephony(transport=httpx.MockTransport(fake.handler))


@pytest.fixture
def actions_api(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Any]:
    """The started API with Google behind a fake account (see actions_support)."""
    from .actions_support import patch_google

    return api, patch_google(monkeypatch)


@pytest.fixture
def shop(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """A real web server on this machine for the HTTP tool; its address is allowed for the test."""
    import threading
    from http.server import ThreadingHTTPServer

    from app.actions import net

    from .actions_support import Shop

    monkeypatch.setattr(net, "ALLOW_LOCAL", True)
    Shop.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), Shop)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture
def interakt(api: TestClient, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Interakt with a key set, answering from a fake vendor."""
    import functools

    from app.providers.base import ProviderKind
    from app.providers.registry import ADAPTERS
    from app.providers.whatsapp.interakt import InteraktWhatsApp

    from .actions_support import Vendor

    monkeypatch.setenv("INTERAKT_API_KEY", "key-1")
    vendor = Vendor()
    adapter = functools.partial(InteraktWhatsApp, httpx.MockTransport(vendor.handler))
    monkeypatch.setitem(ADAPTERS, (ProviderKind.WHATSAPP, "interakt"), adapter)
    yield vendor


@pytest.fixture
def teaching(monkeypatch: pytest.MonkeyPatch) -> Iterator[Vendor]:
    """Gemini (chat, files, embeddings) and Sarvam speech-to-text with canned answers."""
    for key in ("GEMINI_API_KEY", "SARVAM_API_KEY"):
        monkeypatch.setenv(key, "test-key")
    monkeypatch.setenv("AXON_STT_PROVIDER", "sarvam")
    fake = Vendor()
    transport = httpx.MockTransport(fake.handler)
    monkeypatch.setattr(
        common.VendorHealth,
        "client",
        lambda self, timeout=60.0: httpx.AsyncClient(transport=transport),
    )
    yield fake


@pytest.fixture
def receiver(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """A real web server on this machine standing in for a developer's webhook receiver; its
    address is allowed for the test."""
    import threading
    from http.server import ThreadingHTTPServer

    from app.actions import net

    from .developer_support import Receiver

    monkeypatch.setattr(net, "ALLOW_LOCAL", True)
    Receiver.reset()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    Receiver.base = f"http://127.0.0.1:{server.server_port}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield Receiver
    server.shutdown()
