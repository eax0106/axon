"""Each vendor's Pipecat service builds offline (no network until a call starts)."""

from typing import Any

import pytest
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.sarvam.llm import SarvamLLMService
from pipecat.services.sarvam.stt import SarvamSTTService
from pipecat.services.sarvam.tts import SarvamTTSService
from pipecat.services.smallest.stt import SmallestSTTService
from pipecat.services.smallest.tts import SmallestTTSService

from app.models import VoiceTier
from app.providers.base import ProviderKind, ProviderNotConfiguredError
from app.providers.registry import ADAPTERS, VENDOR_KEYS
from engine.legs import voice_legs
from engine.services import SERVICES, Delivery

LANGUAGES = ["te", "hi", "en"]
EXPECTED = [
    (ProviderKind.STT, "sarvam", SarvamSTTService),
    (ProviderKind.STT, "smallest", SmallestSTTService),
    (ProviderKind.LLM, "gemini", GoogleLLMService),
    (ProviderKind.LLM, "sarvam", SarvamLLMService),
    (ProviderKind.TTS, "sarvam", SarvamTTSService),
    (ProviderKind.TTS, "smallest", SmallestTTSService),
    (ProviderKind.TTS, "cartesia", CartesiaTTSService),
]


@pytest.fixture(autouse=True)
def vendor_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for vendors in VENDOR_KEYS.values():
        for keys in vendors.values():
            for key in keys:
                monkeypatch.setenv(key, "test-key")
    for language in ("TE", "HI", "EN"):
        monkeypatch.setenv(f"CARTESIA_VOICE_{language}", f"voice-{language.lower()}")
    for kind in ("STT", "LLM", "TTS"):
        monkeypatch.delenv(f"AXON_{kind}_PROVIDER", raising=False)


def test_every_speech_adapter_has_an_engine_service() -> None:
    speech = {
        key for key in ADAPTERS if key[0] in (ProviderKind.STT, ProviderKind.LLM, ProviderKind.TTS)
    }
    assert speech == set(SERVICES)


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize(("kind", "name", "service"), EXPECTED)
def test_service_builds_for_each_language(
    kind: ProviderKind, name: str, service: type, language: str
) -> None:
    built: Any = SERVICES[(kind, name)](language, Delivery())
    if kind is not ProviderKind.LLM:
        assert str(built._settings.language).startswith(language)
    assert isinstance(built, service)


def test_models_and_voices_are_the_intended_ones() -> None:
    def settings(kind: ProviderKind, name: str) -> Any:
        built: Any = SERVICES[(kind, name)]("te", Delivery())
        return built._settings

    assert settings(ProviderKind.STT, "sarvam").model == "saaras:v4"
    tts = settings(ProviderKind.TTS, "sarvam")
    assert (tts.model, tts.voice) == ("bulbul:v3", "shubh")
    tts = settings(ProviderKind.TTS, "smallest")
    assert (tts.model, tts.voice) == ("lightning_v3.1", "srihari")
    tts = settings(ProviderKind.TTS, "cartesia")
    assert (tts.model, tts.voice) == ("sonic-3.6", "voice-te")
    assert settings(ProviderKind.LLM, "gemini").model == "gemini-2.5-flash"
    assert settings(ProviderKind.LLM, "sarvam").model == "sarvam-105b"


def test_gemini_model_can_be_switched_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AXON_GEMINI_MODEL", "gemini-3.6-flash")
    built: Any = SERVICES[(ProviderKind.LLM, "gemini")]("en", Delivery())
    assert built._settings.model == "gemini-3.6-flash"


def test_cartesia_telugu_and_hindi_need_a_voice_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CARTESIA_VOICE_TE")
    monkeypatch.delenv("CARTESIA_VOICE_EN")
    cartesia = SERVICES[(ProviderKind.TTS, "cartesia")]
    with pytest.raises(ProviderNotConfiguredError) as raised:
        cartesia("te", Delivery())
    assert raised.value.missing_keys == ["CARTESIA_VOICE_TE"]
    assert cartesia("en", Delivery())  # English has a documented default voice


def test_unsupported_language_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported language"):
        SERVICES[(ProviderKind.STT, "sarvam")]("ta", Delivery())


@pytest.mark.parametrize(
    ("tier", "service"),
    [
        (VoiceTier.VALUE, SarvamTTSService),
        (VoiceTier.STANDARD, SmallestTTSService),
        (VoiceTier.PREMIUM, CartesiaTTSService),
    ],
)
def test_voice_legs_use_the_tier_tts(tier: VoiceTier, service: type) -> None:
    stt, llm, tts = voice_legs("hi", tier)
    assert isinstance(stt, SarvamSTTService)
    assert isinstance(llm, GoogleLLMService)
    assert isinstance(tts, service)


def test_voice_legs_without_tier_use_the_selected_tts() -> None:
    assert isinstance(voice_legs("en")[2], SarvamTTSService)


def test_voice_legs_premium_without_key_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CARTESIA_API_KEY")
    with pytest.raises(ProviderNotConfiguredError) as raised:
        voice_legs("en", VoiceTier.PREMIUM)
    assert raised.value.missing_keys == ["CARTESIA_API_KEY"]
