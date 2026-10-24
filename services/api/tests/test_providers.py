from collections.abc import Iterator
from typing import Annotated

import pytest
from app.main import app
from app.providers import registry
from app.providers.base import Provider, ProviderKind
from fastapi import Depends
from fastapi.testclient import TestClient


class _BrokenVendor(Provider):
    """Stands in for an adapter whose vendor rejects the call; only reachable from tests."""

    kind = ProviderKind.STT
    name = "sarvam"

    async def health(self) -> None:
        raise PermissionError("401 invalid api key")


@app.get("/_test/needs-stt")
async def _needs_stt(
    provider: Annotated[Provider, Depends(lambda: registry.require(ProviderKind.STT))],
) -> str:
    return provider.name


@pytest.fixture
def broken_sarvam_adapter() -> Iterator[None]:
    registry.ADAPTERS[(ProviderKind.STT, "sarvam")] = _BrokenVendor
    yield
    del registry.ADAPTERS[(ProviderKind.STT, "sarvam")]


def _row(client: TestClient, kind: str, name: str) -> dict[str, object]:
    rows = client.get("/admin/providers").json()["providers"]
    return next(r for r in rows if r["kind"] == kind and r["name"] == name)


def test_every_vendor_is_missing_key_when_no_keys_are_set(client: TestClient) -> None:
    rows = client.get("/admin/providers").json()["providers"]
    expected = {(k.value, n) for k, vendors in registry.VENDOR_KEYS.items() for n in vendors}
    assert {(r["kind"], r["name"]) for r in rows} == expected
    assert {r["status"] for r in rows} == {"missing_key"}
    assert _row(client, "telephony", "vobiz")["missing_keys"] == [
        "VOBIZ_AUTH_ID",
        "VOBIZ_AUTH_TOKEN",
    ]


def test_empty_value_counts_as_missing(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    assert _row(client, "llm", "gemini")["status"] == "missing_key"


def test_key_present_reports_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CARTESIA_API_KEY", "set-in-test")
    assert _row(client, "tts", "cartesia")["status"] == "configured"


def test_selection_follows_env_and_defaults_to_first_vendor(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _row(client, "tts", "sarvam")["selected"] is True
    monkeypatch.setenv("AXON_TTS_PROVIDER", "cartesia")
    assert _row(client, "tts", "sarvam")["selected"] is False
    assert _row(client, "tts", "cartesia")["selected"] is True


def test_failing_health_check_reports_unhealthy(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, broken_sarvam_adapter: None
) -> None:
    monkeypatch.setenv("SARVAM_API_KEY", "set-in-test")
    row = _row(client, "stt", "sarvam")
    assert row["status"] == "unhealthy"
    assert row["error"] == "PermissionError: 401 invalid api key"


def test_missing_key_answers_503_naming_the_key(client: TestClient) -> None:
    response = client.get("/_test/needs-stt")
    assert response.status_code == 503
    assert response.json() == {
        "error": "provider_not_configured",
        "kind": "stt",
        "provider": "sarvam",
        "missing_keys": ["SARVAM_API_KEY"],
        "detail": "stt provider 'sarvam' needs SARVAM_API_KEY",
    }


def test_unknown_vendor_names_the_selection_variable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AXON_STT_PROVIDER", "nope")
    body = client.get("/_test/needs-stt").json()
    assert body["error"] == "provider_not_configured"
    assert body["missing_keys"] == ["AXON_STT_PROVIDER"]


def test_keys_without_a_built_adapter_still_answer_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SARVAM_API_KEY", "set-in-test")
    response = client.get("/_test/needs-stt")
    assert response.status_code == 503
    assert response.json()["detail"] == "stt adapter 'sarvam' not built yet"


def test_vendor_with_keys_and_adapter_is_returned(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, broken_sarvam_adapter: None
) -> None:
    monkeypatch.setenv("SARVAM_API_KEY", "set-in-test")
    assert client.get("/_test/needs-stt").json() == "sarvam"
