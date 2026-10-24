from collections.abc import Iterator

import pytest
from app.main import app
from app.providers.registry import VENDOR_KEYS
from app.settings import get_settings
from fastapi.testclient import TestClient

ALL_KEYS = sorted(
    {key for vendors in VENDOR_KEYS.values() for keys in vendors.values() for key in keys}
)


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
