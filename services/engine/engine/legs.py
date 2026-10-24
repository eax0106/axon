"""The three AI legs of a call (speech-to-text, LLM, text-to-speech), from the provider registry."""

from typing import Protocol, runtime_checkable

from pipecat.processors.frame_processor import FrameProcessor

from app.providers.base import ProviderKind, ProviderNotConfiguredError
from app.providers.registry import require, tts_for_tier


@runtime_checkable
class PipelineLeg(Protocol):
    """What an STT, LLM or TTS adapter (B3) offers the engine: a Pipecat service for one call."""

    def pipecat_service(self, language: str) -> FrameProcessor: ...


def voice_legs(
    language: str, tier: str | None = None
) -> tuple[FrameProcessor, FrameProcessor, FrameProcessor]:
    """STT, LLM and TTS services for a call, or ProviderNotConfiguredError (served as 503).

    `tier` (value / standard / premium) picks the TTS vendor; without it the selected TTS is used.
    """
    services = []
    for kind in (ProviderKind.STT, ProviderKind.LLM, ProviderKind.TTS):
        provider = tts_for_tier(tier) if kind is ProviderKind.TTS and tier else require(kind)
        if not isinstance(provider, PipelineLeg):
            detail = f"{kind} adapter {provider.name!r} has no pipeline service"
            raise ProviderNotConfiguredError(kind, provider.name, [], detail)
        services.append(provider.pipecat_service(language))
    stt, llm, tts = services
    return stt, llm, tts
