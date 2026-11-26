"""Each vendor's Pipecat service builds offline (no network until a call starts)."""

import asyncio
import json
from typing import Any

import httpx
import openai
import pytest
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.elevenlabs.stt import ElevenLabsRealtimeSTTService
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.sarvam.llm import SarvamLLMService
from pipecat.services.sarvam.stt import SarvamSTTService
from pipecat.services.sarvam.tts import SarvamTTSService
from pipecat.services.smallest.stt import SmallestSTTService
from pipecat.services.smallest.tts import SmallestTTSService
from pipecat.services.soniox.stt import SonioxSTTService

from app.providers.base import ProviderKind, ProviderNotConfiguredError
from app.providers.registry import ADAPTERS, VENDOR_KEYS
from engine.services import SERVICES, Delivery

LANGUAGES = ["te", "hi", "en"]
EXPECTED = [
    (ProviderKind.STT, "sarvam", SarvamSTTService),
    (ProviderKind.STT, "smallest", SmallestSTTService),
    (ProviderKind.STT, "soniox", SonioxSTTService),
    (ProviderKind.STT, "elevenlabs", ElevenLabsRealtimeSTTService),
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
        settings = built._settings  # Soniox takes language hints, the first is the caller's
        heard = settings.language_hints[0] if name == "soniox" else settings.language
        assert str(heard).startswith(language)
    assert isinstance(built, service)


def test_models_and_voices_are_the_intended_ones() -> None:
    def settings(kind: ProviderKind, name: str) -> Any:
        built: Any = SERVICES[(kind, name)]("te", Delivery())
        return built._settings

    assert settings(ProviderKind.STT, "sarvam").model == "saaras:v4"
    assert settings(ProviderKind.STT, "soniox").model == "stt-rt-v6"
    assert settings(ProviderKind.STT, "elevenlabs").model == "scribe_v2_realtime"
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
    ("model", "thinking"),
    [
        ("gemini-2.5-flash", {"thinking_budget": 0}),
        ("gemini-3.5-flash-lite", {"thinking_level": "minimal"}),
    ],
)
def test_gemini_asks_for_its_lowest_thinking(model: str, thinking: dict[str, Any]) -> None:
    """Hidden thinking delays the first word the caller hears; Pipecat sends the lowest setting
    for a model it knows, and this catches an upgrade that stops doing so."""
    built: Any = SERVICES[(ProviderKind.LLM, "gemini")]("en", Delivery(model=model))
    params: dict[str, Any] = {}
    built._maybe_apply_thinking_default(params)
    assert params["thinking_config"] == thinking


def test_sarvam_llm_turns_reasoning_off() -> None:
    """sarvam-105b reasons before answering unless the request carries reasoning_effort: null."""
    sent: list[dict[str, Any]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(400, json={"error": {"message": "not a real vendor"}})

    built: Any = SERVICES[(ProviderKind.LLM, "sarvam")]("te", Delivery())
    built._client = built._client.with_options(
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(answer))
    )
    context = LLMContext(messages=[{"role": "user", "content": "hello"}])
    with pytest.raises(openai.BadRequestError):
        asyncio.run(built.get_chat_completions(context))
    assert "reasoning_effort" in sent[0]
    assert sent[0]["reasoning_effort"] is None
    assert sent[0]["max_tokens"] == 1500


def test_keyterms_reach_every_speech_to_text_vendor_that_takes_them() -> None:
    terms = ("Skyline Habitats", "అనన్య", "Gachibowli")
    hints = Delivery(keyterms=terms)
    sarvam: Any = SERVICES[(ProviderKind.STT, "sarvam")]("te", hints)
    soniox: Any = SERVICES[(ProviderKind.STT, "soniox")]("te", hints)
    eleven: Any = SERVICES[(ProviderKind.STT, "elevenlabs")]("te", hints)

    assert sarvam._keyterms == list(terms)
    assert soniox._settings.context.terms == list(terms)
    assert eleven._settings.keyterms == list(terms)
    # No hints, nothing sent; and Saaras v3 takes none.
    assert SERVICES[(ProviderKind.STT, "sarvam")]("te", Delivery())._keyterms is None  # type: ignore[attr-defined]
    older: Any = SERVICES[(ProviderKind.STT, "sarvam")](
        "te", Delivery(keyterms=terms, model="saaras:v3")
    )
    assert older._keyterms is None


def test_a_calls_keyterms_go_to_every_stt_vendor_of_the_leg_and_no_other_leg() -> None:
    from engine.legs import voice_legs

    stt, llm, tts = voice_legs("te", keyterms=("Skyline Habitats",))
    assert len(stt.services) > 1
    for service in stt.services:
        settings: Any = getattr(service, "_settings", None)
        if isinstance(service, SmallestSTTService):
            continue  # Smallest takes no hints
        if isinstance(service, SonioxSTTService):
            assert settings.context.terms == ["Skyline Habitats"]
        elif isinstance(service, SarvamSTTService):
            assert getattr(service, "_keyterms", None) == ["Skyline Habitats"]
        else:
            assert settings.keyterms == ["Skyline Habitats"]
    for other in (*llm.services, *tts.services):
        assert not getattr(other, "_keyterms", None)
