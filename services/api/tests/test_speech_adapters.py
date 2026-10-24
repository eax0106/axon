import asyncio
import json

import httpx
import pytest

from app.providers.base import Provider, ProviderKind, ProviderNotConfiguredError
from app.providers.registry import ADAPTERS, TIER_TTS, VENDOR_KEYS, require, tts_for_tier
from app.providers.speech.cartesia import CartesiaTTS
from app.providers.speech.gemini import GeminiLLM
from app.providers.speech.sarvam import SarvamLLM, SarvamSTT, SarvamTTS
from app.providers.speech.smallest import SmallestSTT, SmallestTTS

SPEECH = [
    (ProviderKind.STT, "sarvam", SarvamSTT),
    (ProviderKind.STT, "smallest", SmallestSTT),
    (ProviderKind.LLM, "gemini", GeminiLLM),
    (ProviderKind.LLM, "sarvam", SarvamLLM),
    (ProviderKind.TTS, "sarvam", SarvamTTS),
    (ProviderKind.TTS, "smallest", SmallestTTS),
    (ProviderKind.TTS, "cartesia", CartesiaTTS),
]
IDS = [f"{kind}-{name}" for kind, name, _ in SPEECH]


def set_keys(monkeypatch: pytest.MonkeyPatch, kind: ProviderKind, name: str) -> None:
    for key in VENDOR_KEYS[kind][name]:
        monkeypatch.setenv(key, "test-key")
    monkeypatch.setenv(f"AXON_{kind.upper()}_PROVIDER", name)


@pytest.mark.parametrize(("kind", "name", "adapter"), SPEECH, ids=IDS)
def test_adapter_registered_and_required_when_keys_are_set(
    monkeypatch: pytest.MonkeyPatch, kind: ProviderKind, name: str, adapter: type[Provider]
) -> None:
    assert ADAPTERS[(kind, name)] is adapter
    set_keys(monkeypatch, kind, name)
    assert isinstance(require(kind), adapter)


@pytest.mark.parametrize(("kind", "name", "adapter"), SPEECH, ids=IDS)
def test_missing_key_is_503_provider_not_configured(
    monkeypatch: pytest.MonkeyPatch, kind: ProviderKind, name: str, adapter: type[Provider]
) -> None:
    for key in VENDOR_KEYS[kind][name]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(f"AXON_{kind.upper()}_PROVIDER", name)
    with pytest.raises(ProviderNotConfiguredError) as raised:
        require(kind)
    assert raised.value.missing_keys == list(VENDOR_KEYS[kind][name])


def health_request(monkeypatch: pytest.MonkeyPatch, kind: ProviderKind, name: str) -> httpx.Request:
    """Run the adapter's health() against a transport that records the request it was sent."""
    set_keys(monkeypatch, kind, name)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    adapter = ADAPTERS[(kind, name)]
    asyncio.run(adapter(transport=httpx.MockTransport(handler)).health())  # type: ignore[call-arg]
    return seen[0]


def test_health_sarvam_posts_language_id_with_subscription_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for kind in (ProviderKind.STT, ProviderKind.LLM, ProviderKind.TTS):
        request = health_request(monkeypatch, kind, "sarvam")
        assert (request.method, str(request.url)) == ("POST", "https://api.sarvam.ai/text-lid")
        assert request.headers["api-subscription-key"] == "test-key"
        assert json.loads(request.content) == {"input": "hello"}


def test_health_smallest_lists_voices_with_bearer_key(monkeypatch: pytest.MonkeyPatch) -> None:
    for kind in (ProviderKind.STT, ProviderKind.TTS):
        request = health_request(monkeypatch, kind, "smallest")
        url = "https://api.smallest.ai/waves/v1/lightning-v3.1/get_voices"
        assert (request.method, str(request.url)) == ("GET", url)
        assert request.headers["authorization"] == "Bearer test-key"


def test_health_cartesia_lists_one_voice_with_version_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = health_request(monkeypatch, ProviderKind.TTS, "cartesia")
    assert str(request.url) == "https://api.cartesia.ai/voices?limit=1"
    assert request.headers["authorization"] == "Bearer test-key"
    assert request.headers["cartesia-version"] == "2026-08-14"


def test_health_gemini_lists_one_model_with_goog_key_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = health_request(monkeypatch, ProviderKind.LLM, "gemini")
    url = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1"
    assert str(request.url) == url
    assert request.headers["x-goog-api-key"] == "test-key"


def test_health_raises_when_the_vendor_rejects_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    set_keys(monkeypatch, ProviderKind.TTS, "sarvam")
    transport = httpx.MockTransport(lambda _: httpx.Response(403, json={"error": "invalid key"}))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(SarvamTTS(transport=transport).health())


def test_tier_maps_value_standard_premium_to_sarvam_smallest_cartesia(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert TIER_TTS == {"value": "sarvam", "standard": "smallest", "premium": "cartesia"}
    for tier, name in TIER_TTS.items():
        set_keys(monkeypatch, ProviderKind.TTS, name)
        assert tts_for_tier(tier).name == name


def test_tier_unknown_is_rejected_and_missing_key_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="unknown voice tier"):
        tts_for_tier("gold")
    monkeypatch.delenv("CARTESIA_API_KEY", raising=False)
    with pytest.raises(ProviderNotConfiguredError) as raised:
        tts_for_tier("premium")
    assert raised.value.missing_keys == ["CARTESIA_API_KEY"]
