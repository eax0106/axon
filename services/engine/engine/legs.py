"""The three AI legs of a call (speech-to-text, LLM, text-to-speech), from the provider registry."""

from pipecat.processors.frame_processor import FrameProcessor

from app.models import VoiceTier
from app.providers.base import Provider, ProviderKind, ProviderNotConfiguredError
from app.providers.registry import require, tts_for_tier
from engine.services import SERVICES


def _service(provider: Provider, language: str) -> FrameProcessor:
    factory = SERVICES.get((provider.kind, provider.name))
    if factory is None:
        detail = f"{provider.kind} adapter {provider.name!r} has no pipeline service"
        raise ProviderNotConfiguredError(provider.kind, provider.name, [], detail)
    return factory(language)


def voice_legs(
    language: str, tier: VoiceTier | None = None
) -> tuple[FrameProcessor, FrameProcessor, FrameProcessor]:
    """STT, LLM and TTS services for a call, or ProviderNotConfiguredError (served as 503).

    `tier` picks the TTS vendor; without it the selected TTS is used.
    """
    tts = tts_for_tier(tier) if tier else require(ProviderKind.TTS)
    stt, llm = require(ProviderKind.STT), require(ProviderKind.LLM)
    return _service(stt, language), _service(llm, language), _service(tts, language)
