"""Each adapter builds its real Pipecat service offline (no network until a call starts)."""

import os
from typing import Any

import pytest
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.sarvam.llm import SarvamLLMService
from pipecat.services.sarvam.stt import SarvamSTTService
from pipecat.services.sarvam.tts import SarvamTTSService
from pipecat.services.smallest.stt import SmallestSTTService
from pipecat.services.smallest.tts import SmallestTTSService

from app.providers.base import ProviderKind, ProviderNotConfiguredError
from app.providers.registry import VENDOR_KEYS, require
from engine.legs import voice_legs

LANGUAGES = ["te", "hi", "en"]
SERVICES = [
    (ProviderKind.STT, "sarvam", SarvamSTTService),
    (ProviderKind.STT, "smallest", SmallestSTTService),
    (ProviderKind.LLM, "gemini", GoogleLLMService),
    (ProviderKind.LLM, "sarvam", SarvamLLMService),
    (ProviderKind.TTS, "sarvam", SarvamTTSService),
    (ProviderKind.TTS, "smallest", SmallestTTSService),
    (ProviderKind.TTS, "cartesia", CartesiaTTSService),
]


def leg(kind: ProviderKind) -> Any:
    return require(kind)


@pytest.fixture(autouse=True)
def vendor_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for vendors in VENDOR_KEYS.values():
        for keys in vendors.values():
            for key in keys:
                monkeypatch.setenv(key, "test-key")
    for language in ("TE", "HI", "EN"):
        monkeypatch.setenv(f"CARTESIA_VOICE_{language}", f"voice-{language.lower()}")


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize(("kind", "name", "service"), SERVICES)
def test_adapter_builds_its_pipecat_service(
    monkeypatch: pytest.MonkeyPatch, kind: ProviderKind, name: str, service: type, language: str
) -> None:
    monkeypatch.setenv(f"AXON_{kind.upper()}_PROVIDER", name)
    built: Any = leg(kind).pipecat_service(language)
    if kind is not ProviderKind.LLM:
        assert str(built._settings.language).startswith(language)
    assert isinstance(built, service)


def test_models_and_voices_are_the_intended_ones(monkeypatch: pytest.MonkeyPatch) -> None:
    def build(kind: ProviderKind, name: str, language: str = "te") -> Any:
        monkeypatch.setenv(f"AXON_{kind.upper()}_PROVIDER", name)
        return leg(kind).pipecat_service(language)

    assert build(ProviderKind.STT, "sarvam")._settings.model == "saaras:v4"
    tts = build(ProviderKind.TTS, "sarvam")._settings
    assert (tts.model, tts.voice) == ("bulbul:v3", "shubh")
    tts = build(ProviderKind.TTS, "smallest")._settings
    assert (tts.model, tts.voice) == ("lightning_v3.1", "srihari")
    tts = build(ProviderKind.TTS, "cartesia")._settings
    assert (tts.model, tts.voice) == ("sonic-3.6", "voice-te")
    assert build(ProviderKind.LLM, "gemini")._settings.model == "gemini-2.5-flash"
    assert build(ProviderKind.LLM, "sarvam")._settings.model == "sarvam-105b"


def test_cartesia_telugu_and_hindi_need_a_voice_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CARTESIA_VOICE_TE")
    monkeypatch.delenv("CARTESIA_VOICE_EN")
    monkeypatch.setenv("AXON_TTS_PROVIDER", "cartesia")
    with pytest.raises(ProviderNotConfiguredError) as raised:
        leg(ProviderKind.TTS).pipecat_service("te")
    assert raised.value.missing_keys == ["CARTESIA_VOICE_TE"]
    assert leg(ProviderKind.TTS).pipecat_service("en")


def test_unsupported_language_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="unsupported language"):
        leg(ProviderKind.STT).pipecat_service("ta")


@pytest.mark.parametrize(
    ("tier", "service"),
    [
        ("value", SarvamTTSService),
        ("standard", SmallestTTSService),
        ("premium", CartesiaTTSService),
    ],
)
def test_voice_legs_use_the_tier_tts(
    monkeypatch: pytest.MonkeyPatch, tier: str, service: type
) -> None:
    for kind in ("STT", "LLM", "TTS"):
        monkeypatch.delenv(f"AXON_{kind}_PROVIDER", raising=False)
    stt, llm, tts = voice_legs("hi", tier)
    assert isinstance(stt, SarvamSTTService)
    assert isinstance(llm, GoogleLLMService)
    assert isinstance(tts, service)
    assert os.environ["SARVAM_API_KEY"]


def test_voice_legs_without_tier_use_the_selected_tts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AXON_TTS_PROVIDER", raising=False)
    assert isinstance(voice_legs("en")[2], SarvamTTSService)
