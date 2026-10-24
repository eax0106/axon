"""The three AI legs of a call (speech-to-text, LLM, text-to-speech), from the provider registry."""

from pipecat.processors.frame_processor import FrameProcessor

from app.models import Voice, VoiceTier
from app.providers.base import Provider, ProviderKind, ProviderNotConfiguredError
from app.providers.registry import require, resolve, tts_for_tier
from engine.services import SERVICES, Delivery


def _service(provider: Provider, language: str, delivery: Delivery) -> FrameProcessor:
    factory = SERVICES.get((provider.kind, provider.name))
    if factory is None:
        detail = f"{provider.kind} adapter {provider.name!r} has no pipeline service"
        raise ProviderNotConfiguredError(provider.kind, provider.name, [], detail)
    return factory(language, delivery)


def voice_legs(
    language: str,
    tier: VoiceTier | None = None,
    voice: Voice | None = None,
    speed: float = 1.0,
) -> tuple[FrameProcessor, FrameProcessor, FrameProcessor]:
    """STT, LLM and TTS services for a call, or ProviderNotConfiguredError (served as 503).

    A `voice` row (from the voices table) decides the TTS vendor and the voice id. Otherwise
    `tier` picks the vendor, and without either the selected TTS is used with its default voice.
    """
    if voice is not None:
        tts = resolve(ProviderKind.TTS, voice.provider)
    elif tier is not None:
        tts = tts_for_tier(tier)
    else:
        tts = require(ProviderKind.TTS)
    delivery = Delivery(voice_id=voice.provider_voice_id if voice else None, speed=speed)
    stt, llm = require(ProviderKind.STT), require(ProviderKind.LLM)
    return (
        _service(stt, language, delivery),
        _service(llm, language, delivery),
        _service(tts, language, delivery),
    )
