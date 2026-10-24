"""Real-use contract tests: each vendor service synthesizes, transcribes or completes for real, in
Telugu, Hindi and English. They prove the model ids, voice ids and language support that a health
check cannot. Skipped until the vendor's key exists (`requires_keys`).

`run_until` drives one service in a minimal Pipecat pipeline and returns the first frame that
matches. `test_run_until_*` pins that harness offline with a stand-in processor.
"""

import asyncio
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    LLMContextFrame,
    LLMTextFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from app.providers.base import ProviderKind
from engine.services import SERVICES

FIXTURES = Path(__file__).parent / "fixtures"
LANGUAGES = ["te", "hi", "en"]
PHRASES = {
    "en": "Hello, how are you today?",
    "hi": "नमस्ते, आप कैसे हैं?",
    "te": "నమస్కారం, మీరు ఎలా ఉన్నారు?",
}
TIMEOUT_S = 30.0
CHUNK_BYTES = 640  # 20 ms of 16 kHz mono 16-bit audio


async def run_until(
    service: FrameProcessor, frames: list[Frame], match: Callable[[Frame], bool]
) -> Frame:
    """Queue `frames` into `service` and return the first frame it emits that `match` accepts."""
    found: list[Frame] = []
    done = asyncio.Event()

    class Sink(FrameProcessor):
        async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
            await super().process_frame(frame, direction)
            if not found and match(frame):
                found.append(frame)
                done.set()
            await self.push_frame(frame, direction)

    params = PipelineParams(audio_in_sample_rate=16000, audio_out_sample_rate=16000)
    task = PipelineTask(Pipeline([service, Sink()]), params=params, cancel_on_idle_timeout=False)
    run = asyncio.create_task(PipelineRunner(handle_sigint=False).run(task))
    try:
        await task.queue_frames(frames)
        await asyncio.wait_for(done.wait(), TIMEOUT_S)
    finally:
        await task.cancel()
        await run
    return found[0]


def speech_frames(language: str) -> list[Frame]:
    with wave.open(str(FIXTURES / f"hello_{language}.wav")) as clip:
        assert (clip.getframerate(), clip.getnchannels(), clip.getsampwidth()) == (16000, 1, 2)
        audio = clip.readframes(clip.getnframes())
    audio += bytes(CHUNK_BYTES * 25)  # half a second of silence so the vendor sees the turn end
    chunks = [audio[i : i + CHUNK_BYTES] for i in range(0, len(audio), CHUNK_BYTES)]
    return [
        VADUserStartedSpeakingFrame(),
        *[InputAudioRawFrame(audio=chunk, sample_rate=16000, num_channels=1) for chunk in chunks],
        VADUserStoppedSpeakingFrame(),
    ]


def is_audio(frame: Frame) -> bool:
    return isinstance(frame, TTSAudioRawFrame) and len(frame.audio) > 0


def is_transcript(frame: Frame) -> bool:
    return isinstance(frame, TranscriptionFrame) and bool(frame.text.strip())


def is_text(frame: Frame) -> bool:
    return isinstance(frame, LLMTextFrame) and bool(frame.text.strip())


def build(kind: ProviderKind, name: str, language: str) -> FrameProcessor:
    return SERVICES[(kind, name)](language)


@pytest.mark.parametrize("language", LANGUAGES)
class TestRealUse:
    @pytest.mark.requires_keys("SARVAM_API_KEY")
    def test_sarvam_tts_speaks(self, language: str) -> None:
        service = build(ProviderKind.TTS, "sarvam", language)
        asyncio.run(run_until(service, [TTSSpeakFrame(PHRASES[language])], is_audio))

    @pytest.mark.requires_keys("SMALLEST_API_KEY")
    def test_smallest_tts_speaks(self, language: str) -> None:
        service = build(ProviderKind.TTS, "smallest", language)
        asyncio.run(run_until(service, [TTSSpeakFrame(PHRASES[language])], is_audio))

    @pytest.mark.requires_keys("CARTESIA_API_KEY", "CARTESIA_VOICE_HI", "CARTESIA_VOICE_TE")
    def test_cartesia_tts_speaks(self, language: str) -> None:
        service = build(ProviderKind.TTS, "cartesia", language)
        asyncio.run(run_until(service, [TTSSpeakFrame(PHRASES[language])], is_audio))

    @pytest.mark.requires_keys("SARVAM_API_KEY")
    def test_sarvam_stt_transcribes(self, language: str) -> None:
        service = build(ProviderKind.STT, "sarvam", language)
        asyncio.run(run_until(service, speech_frames(language), is_transcript))

    @pytest.mark.requires_keys("SMALLEST_API_KEY")
    def test_smallest_stt_transcribes(self, language: str) -> None:
        service = build(ProviderKind.STT, "smallest", language)
        asyncio.run(run_until(service, speech_frames(language), is_transcript))

    @pytest.mark.requires_keys("GEMINI_API_KEY")
    def test_gemini_completes(self, language: str) -> None:
        service = build(ProviderKind.LLM, "gemini", language)
        asyncio.run(run_until(service, [llm_request()], is_text))

    @pytest.mark.requires_keys("SARVAM_API_KEY")
    def test_sarvam_llm_completes(self, language: str) -> None:
        service = build(ProviderKind.LLM, "sarvam", language)
        asyncio.run(run_until(service, [llm_request()], is_text))


def llm_request() -> LLMContextFrame:
    messages: Any = [{"role": "user", "content": "Reply with the single word: ok"}]
    return LLMContextFrame(LLMContext(messages))


class _SpeaksWhenAsked(FrameProcessor):
    """Test-only stand-in that answers a TTSSpeakFrame with one audio frame."""

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSSpeakFrame):
            await self.push_frame(
                TTSAudioRawFrame(audio=b"\x01\x00" * 160, sample_rate=16000, num_channels=1)
            )
        else:
            await self.push_frame(frame, direction)


def test_run_until_returns_the_first_matching_frame() -> None:
    frame = asyncio.run(run_until(_SpeaksWhenAsked(), [TTSSpeakFrame("hi")], is_audio))
    assert isinstance(frame, TTSAudioRawFrame)
    assert len(frame.audio) == 320


def test_run_until_times_out_when_nothing_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(__name__ + ".TIMEOUT_S", 0.5)
    with pytest.raises(TimeoutError):
        asyncio.run(run_until(_SpeaksWhenAsked(), [], is_audio))


@pytest.mark.parametrize("language", LANGUAGES)
def test_speech_fixture_is_a_16khz_mono_clip_with_the_end_marker(language: str) -> None:
    frames = speech_frames(language)
    assert isinstance(frames[0], VADUserStartedSpeakingFrame)
    assert isinstance(frames[-1], VADUserStoppedSpeakingFrame)
    assert all(
        isinstance(f, InputAudioRawFrame) and len(f.audio) <= CHUNK_BYTES for f in frames[1:-1]
    )
