"""Live call events and the usage meter.

Events go to Redis channel `call:<call_id>:events` as JSON; the API serves them to the
dashboard over an authenticated WebSocket (GET /calls/{id}/live).
"""

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Any

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    InputAudioRawFrame,
    InterruptionFrame,
    MetricsFrame,
    TranscriptionFrame,
    TTSTextFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.metrics.metrics import LLMUsageMetricsData, TTSUsageMetricsData
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.processors.frame_processor import FrameProcessor
from redis.asyncio import Redis

from app.live import channel

EventSink = Callable[[dict[str, Any]], Awaitable[None]]


def redis_sink(redis: Redis, call_id: str) -> EventSink:
    async def publish(event: dict[str, Any]) -> None:
        await redis.publish(channel(call_id), json.dumps({"at": time.time(), **event}))

    return publish


@dataclass
class Usage:
    """What a call consumed. Billing (B7) turns this into credits; billing starts at pickup."""

    answered_at: float | None = None
    ended_at: float | None = None
    caller_audio_s: float = 0.0
    llm_prompt_tokens: int = 0
    llm_completion_tokens: int = 0
    tts_characters: int = 0

    @property
    def duration_s(self) -> float:
        if self.answered_at is None:
            return 0.0
        return max(0.0, (self.ended_at or time.monotonic()) - self.answered_at)

    def as_event(self) -> dict[str, Any]:
        fields = asdict(self)
        del fields["answered_at"], fields["ended_at"]
        return {"type": "usage", "duration_s": round(self.duration_s, 3), **fields}


_STATES: dict[type, str] = {
    UserStartedSpeakingFrame: "user_started_speaking",
    UserStoppedSpeakingFrame: "user_stopped_speaking",
    BotStartedSpeakingFrame: "bot_started_speaking",
    BotStoppedSpeakingFrame: "bot_stopped_speaking",
    InterruptionFrame: "interruption",
}


class CallObserver(BaseObserver):
    """Publishes each meaningful frame once and meters usage.

    A frame is observed at every hop through the pipeline, so audio is counted only where it
    leaves the input transport and other frames are de-duplicated by id.
    """

    def __init__(self, publish: EventSink, audio_source: FrameProcessor) -> None:
        super().__init__()
        self.usage = Usage()
        self._publish = publish
        self._audio_source = audio_source
        self._seen: set[int] = set()

    async def on_push_frame(self, data: FramePushed) -> None:
        frame = data.frame
        if isinstance(frame, InputAudioRawFrame):
            if data.source is self._audio_source:
                if self.usage.answered_at is None:
                    self.usage.answered_at = time.monotonic()
                self.usage.caller_audio_s += len(frame.audio) / (2 * frame.sample_rate)
            return
        if frame.id in self._seen:
            return
        event = self._event(frame)
        if event is None:
            return
        self._seen.add(frame.id)
        if event:
            await self._publish(event)

    def _event(self, frame: Any) -> dict[str, Any] | None:
        """The event to publish for `frame`, {} to only meter it, None to ignore it."""
        if type(frame) in _STATES:
            return {"type": _STATES[type(frame)]}
        if isinstance(frame, TranscriptionFrame):
            return {"type": "user_transcript", "text": frame.text}
        if isinstance(frame, TTSTextFrame):
            return {"type": "bot_text", "text": frame.text}
        if isinstance(frame, MetricsFrame):
            for item in frame.data:
                if isinstance(item, LLMUsageMetricsData):
                    self.usage.llm_prompt_tokens += item.value.prompt_tokens
                    self.usage.llm_completion_tokens += item.value.completion_tokens
                elif isinstance(item, TTSUsageMetricsData):
                    self.usage.tts_characters += item.value
            return {}
        return None
