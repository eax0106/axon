"""The Pipecat service each registered vendor offers a call, keyed like `registry.ADAPTERS`.

Adapters in the API package only know keys and health; the engine alone runs Pipecat. Voice ids
below are fixed per vendor until B4 reads them from the `voices` table.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass

from pipecat.processors.frame_processor import FrameProcessor
from pipecat.services.cartesia.tts import CartesiaTTSService, GenerationConfig
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.sarvam.llm import SarvamLLMService
from pipecat.services.sarvam.stt import SarvamSTTService
from pipecat.services.sarvam.tts import SarvamTTSService
from pipecat.services.smallest.stt import SmallestSTTService
from pipecat.services.smallest.tts import SmallestTTSService
from pipecat.transcriptions.language import Language

from app.providers.base import ProviderKind, ProviderNotConfiguredError
from app.providers.speech import cartesia, gemini, sarvam, smallest
from app.providers.speech.cartesia import VOICE_ENV
from app.providers.speech.common import LANGUAGES

SARVAM_TTS_VOICE = "shubh"  # fallback for a call with no employee voice
# Voices from Smallest's catalog that speak each V1 language.
SMALLEST_VOICES = {"te": "srihari", "hi": "devansh", "en": "avery"}
CARTESIA_ENGLISH_VOICE = "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4"


@dataclass(frozen=True)
class Delivery:
    """How a call should sound: the chosen vendor voice (None = built-in default) and speed."""

    voice_id: str | None = None
    speed: float = 1.0


def language(code: str) -> Language:
    if code not in LANGUAGES:
        raise ValueError(f"unsupported language {code!r}; V1 speaks {', '.join(LANGUAGES)}")
    return Language(code)


def _sarvam_stt(code: str, _: Delivery) -> FrameProcessor:
    return SarvamSTTService(
        api_key=os.environ["SARVAM_API_KEY"],
        mode="codemix",
        settings=SarvamSTTService.Settings(model=sarvam.STT_MODEL, language=language(code)),
    )


def _sarvam_tts(code: str, delivery: Delivery) -> FrameProcessor:
    return SarvamTTSService(
        api_key=os.environ["SARVAM_API_KEY"],
        settings=SarvamTTSService.Settings(
            model=sarvam.TTS_MODEL,
            voice=delivery.voice_id or SARVAM_TTS_VOICE,
            language=language(code),
            pace=delivery.speed,
        ),
    )


def _sarvam_llm(code: str, _: Delivery) -> FrameProcessor:
    language(code)  # reject languages outside V1
    # ponytail: Sarvam's reasoning counts against max tokens, so keep the cap at 1500 or more.
    return SarvamLLMService(
        api_key=os.environ["SARVAM_API_KEY"],
        settings=SarvamLLMService.Settings(model=sarvam.LLM_MODEL, max_tokens=1500),
    )


def _smallest_stt(code: str, _: Delivery) -> FrameProcessor:
    return SmallestSTTService(
        api_key=os.environ["SMALLEST_API_KEY"],
        settings=SmallestSTTService.Settings(language=language(code)),
    )


def _smallest_tts(code: str, delivery: Delivery) -> FrameProcessor:
    return SmallestTTSService(
        api_key=os.environ["SMALLEST_API_KEY"],
        settings=SmallestTTSService.Settings(
            model=smallest.TTS_MODEL,
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
            model=cartesia.MODEL,
            voice=_cartesia_voice(code, delivery),
            language=language(code),
            # Cartesia accepts 0.6 to 1.5.
            generation_config=GenerationConfig(speed=min(1.5, max(0.6, delivery.speed))),
        ),
    )


def _gemini_llm(code: str, _: Delivery) -> FrameProcessor:
    language(code)
    return GoogleLLMService(
        api_key=os.environ["GEMINI_API_KEY"],
        settings=GoogleLLMService.Settings(model=gemini.model()),
    )


SERVICES: dict[tuple[ProviderKind, str], Callable[[str, Delivery], FrameProcessor]] = {
    (ProviderKind.STT, "sarvam"): _sarvam_stt,
    (ProviderKind.STT, "smallest"): _smallest_stt,
    (ProviderKind.LLM, "gemini"): _gemini_llm,
    (ProviderKind.LLM, "sarvam"): _sarvam_llm,
    (ProviderKind.TTS, "sarvam"): _sarvam_tts,
    (ProviderKind.TTS, "smallest"): _smallest_tts,
    (ProviderKind.TTS, "cartesia"): _cartesia_tts,
}
