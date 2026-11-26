"""The Pipecat service each registered vendor offers a call, keyed like `registry.ADAPTERS`.

Adapters in the API package only know keys and health; the engine alone runs Pipecat. Voice ids
below are fixed per vendor until B4 reads them from the `voices` table.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pipecat.processors.frame_processor import FrameProcessor
from pipecat.services.cartesia.tts import CartesiaTTSService, GenerationConfig
from pipecat.services.elevenlabs.stt import ElevenLabsRealtimeSTTService
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.sarvam.llm import SarvamLLMService
from pipecat.services.sarvam.stt import SarvamSTTService
from pipecat.services.sarvam.tts import SarvamTTSService
from pipecat.services.smallest.stt import SmallestSTTService
from pipecat.services.smallest.tts import SmallestTTSService
from pipecat.services.soniox.stt import SonioxContextObject, SonioxSTTService
from pipecat.transcriptions.language import Language

from app.providers.base import ProviderKind, ProviderNotConfiguredError
from app.providers.speech import cartesia, elevenlabs, gemini, sarvam, smallest, soniox
from app.providers.speech.cartesia import VOICE_ENV
from app.providers.speech.common import LANGUAGES

SARVAM_TTS_VOICE = "shubh"  # fallback for a call with no employee voice
# Voices from Smallest's catalog that speak each V1 language.
SMALLEST_VOICES = {"te": "srihari", "hi": "devansh", "en": "avery"}
CARTESIA_ENGLISH_VOICE = "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4"


# A caller hears silence while the LLM thinks: an answer that has not started (or stalls) this long
# counts as a failure, and the call moves to the backup LLM instead of waiting on the vendor.
LLM_TIMEOUT_S = 10.0


@dataclass(frozen=True)
class Delivery:
    """How a leg's service is built: the chosen vendor voice (None = built-in default), speed, and
    model (None = the vendor's default; set for the vendor the call stack starts the leg on)."""

    voice_id: str | None = None
    speed: float = 1.0
    model: str | None = None
    keyterms: tuple[str, ...] = ()  # names the speech-to-text should hear right (STT legs only)


def language(code: str) -> Language:
    if code not in LANGUAGES:
        raise ValueError(f"unsupported language {code!r}; V1 speaks {', '.join(LANGUAGES)}")
    return Language(code)


def _sarvam_stt(code: str, delivery: Delivery) -> FrameProcessor:
    model = delivery.model or sarvam.STT_MODEL
    return SarvamSTTService(
        api_key=os.environ["SARVAM_API_KEY"],
        mode="codemix",
        # Only Saaras v4 takes keyterms; an older model would refuse the connection.
        keyterms=list(delivery.keyterms) if delivery.keyterms and model == "saaras:v4" else None,
        settings=SarvamSTTService.Settings(model=model, language=language(code)),
    )


def _sarvam_tts(code: str, delivery: Delivery) -> FrameProcessor:
    return SarvamTTSService(
        api_key=os.environ["SARVAM_API_KEY"],
        settings=SarvamTTSService.Settings(
            model=delivery.model or sarvam.TTS_MODEL,
            voice=delivery.voice_id or SARVAM_TTS_VOICE,
            language=language(code),
            pace=delivery.speed,
        ),
    )


class _SarvamLLM(SarvamLLMService):
    """Sarvam's LLM with the call's timeout and no silent retries: the backup vendor retries."""

    def create_client(self, *args: Any, **kwargs: Any) -> Any:
        client = super().create_client(*args, **kwargs)
        return client.with_options(timeout=LLM_TIMEOUT_S, max_retries=0)


def _sarvam_llm(code: str, delivery: Delivery) -> FrameProcessor:
    language(code)  # reject languages outside V1
    # sarvam-105b reasons before it answers unless reasoning_effort is an explicit null, and on a
    # call that only delays the first word. Pipecat's own setting drops a None, so it rides in
    # extra_body. ponytail: the 1500 cap still leaves room if a model reasons anyway.
    return _SarvamLLM(
        api_key=os.environ["SARVAM_API_KEY"],
        settings=SarvamLLMService.Settings(
            model=delivery.model or sarvam.LLM_MODEL,
            max_tokens=1500,
            extra={"extra_body": {"reasoning_effort": None}},
        ),
    )


def _smallest_stt(code: str, delivery: Delivery) -> FrameProcessor:
    settings = SmallestSTTService.Settings(language=language(code))
    if delivery.model:
        settings.model = delivery.model
    return SmallestSTTService(
        api_key=os.environ["SMALLEST_API_KEY"],
        settings=settings,
    )


def _soniox_stt(code: str, delivery: Delivery) -> FrameProcessor:
    # Pipecat's VAD ends the turn (vad_force_turn_endpoint, the default), as for every vendor.
    return SonioxSTTService(
        api_key=os.environ["SONIOX_API_KEY"],
        settings=SonioxSTTService.Settings(
            model=delivery.model or soniox.RT_MODEL,
            language_hints=[language(hint) for hint in soniox.hints(code)],
            context=SonioxContextObject(terms=list(delivery.keyterms))
            if delivery.keyterms
            else None,
        ),
    )


def _elevenlabs_stt(code: str, delivery: Delivery) -> FrameProcessor:
    return ElevenLabsRealtimeSTTService(
        api_key=os.environ["ELEVENLABS_API_KEY"],
        settings=ElevenLabsRealtimeSTTService.Settings(
            model=delivery.model or elevenlabs.RT_MODELS[0],
            language=language(code),
            keyterms=list(delivery.keyterms) if delivery.keyterms else None,
        ),
    )


def _smallest_tts(code: str, delivery: Delivery) -> FrameProcessor:
    return SmallestTTSService(
        api_key=os.environ["SMALLEST_API_KEY"],
        settings=SmallestTTSService.Settings(
            model=delivery.model or smallest.TTS_MODEL,
            voice=delivery.voice_id or SMALLEST_VOICES[code],
            language=language(code),
            speed=delivery.speed,
        ),
    )


def _cartesia_voice(code: str, delivery: Delivery) -> str:
    if delivery.voice_id:
        return delivery.voice_id
    if language(code) == Language.EN:
        return os.environ.get("CARTESIA_VOICE_EN") or CARTESIA_ENGLISH_VOICE
    var = VOICE_ENV[code]
    voice = os.environ.get(var)
    if not voice:
        detail = f"tts provider 'cartesia' needs {var}"
        raise ProviderNotConfiguredError(ProviderKind.TTS, "cartesia", [var], detail)
    return voice


def _cartesia_tts(code: str, delivery: Delivery) -> FrameProcessor:
    return CartesiaTTSService(
        api_key=os.environ["CARTESIA_API_KEY"],
        settings=CartesiaTTSService.Settings(
            model=delivery.model or cartesia.MODEL,
            voice=_cartesia_voice(code, delivery),
            language=language(code),
            # Cartesia accepts 0.6 to 1.5.
            generation_config=GenerationConfig(speed=min(1.5, max(0.6, delivery.speed))),
        ),
    )


def _gemini_llm(code: str, delivery: Delivery) -> FrameProcessor:
    language(code)
    return GoogleLLMService(
        api_key=os.environ["GEMINI_API_KEY"],
        settings=GoogleLLMService.Settings(model=delivery.model or gemini.model()),
        stream_idle_timeout_secs=LLM_TIMEOUT_S,
    )


SERVICES: dict[tuple[ProviderKind, str], Callable[[str, Delivery], FrameProcessor]] = {
    (ProviderKind.STT, "sarvam"): _sarvam_stt,
    (ProviderKind.STT, "smallest"): _smallest_stt,
    (ProviderKind.STT, "soniox"): _soniox_stt,
    (ProviderKind.STT, "elevenlabs"): _elevenlabs_stt,
    (ProviderKind.LLM, "gemini"): _gemini_llm,
    (ProviderKind.LLM, "sarvam"): _sarvam_llm,
    (ProviderKind.TTS, "sarvam"): _sarvam_tts,
    (ProviderKind.TTS, "smallest"): _smallest_tts,
    (ProviderKind.TTS, "cartesia"): _cartesia_tts,
}
