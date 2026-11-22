"""Live call events and the usage meter.

Events go to Redis channel `call:<call_id>:events` as JSON; the API serves them to the
dashboard over an authenticated WebSocket (GET /calls/{id}/live).
"""

import json
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
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
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.metrics.metrics import LLMUsageMetricsData, TTFBMetricsData, TTSUsageMetricsData
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.processors.frame_processor import FrameProcessor
from redis.asyncio import Redis

from app.live import channel

EventSink = Callable[[dict[str, Any]], Awaitable[None]]
Meter = tuple[str, str, str]  # (kind, vendor, unit): what a vendor's usage is priced in


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
    # How long each caller waited for a reply: from their last sound to the reply's first audio
    # leaving the engine (the carrier's own delay comes on top). Speed work is measured from this.
    response_ms: list[int] = field(default_factory=list)
    ttfb_ms: dict[str, list[int]] = field(default_factory=dict)  # leg kind -> each request's
    # The same usage per vendor, for provider costs: a call that failed over used two vendors.
    meters: dict[Meter, float] = field(default_factory=lambda: defaultdict(float))

    @property
    def duration_s(self) -> float:
        if self.answered_at is None:
            return 0.0
        return max(0.0, (self.ended_at or time.monotonic()) - self.answered_at)

    def as_event(self) -> dict[str, Any]:
        fields = asdict(self)
        del fields["answered_at"], fields["ended_at"], fields["meters"]
        meters = [
            {"kind": kind, "vendor": vendor, "unit": unit, "amount": round(amount, 3)}
            for (kind, vendor, unit), amount in sorted(self.meters.items())
        ]
        return {
            "type": "usage",
            "duration_s": round(self.duration_s, 3),
            **fields,
            "meters": meters,
        }


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

    def __init__(
        self,
        publish: EventSink,
        audio_source: FrameProcessor,
        vendor_of: Callable[[str], tuple[str, str] | None] = lambda _: None,
        listening: Callable[[], str | None] = lambda: None,
    ) -> None:
        """`vendor_of` names the (kind, vendor) of a processor by its name; `listening` is the
        speech-to-text vendor active now, which the caller's audio is streamed to."""
        super().__init__()
        self.usage = Usage()
        self._publish = publish
        self._audio_source = audio_source
        self._vendor_of = vendor_of
        self._listening = listening
        self._seen: set[int] = set()
        self._caller_quiet_at: float | None = None  # the caller's last sound, until a reply starts

    async def on_push_frame(self, data: FramePushed) -> None:
        frame = data.frame
        if isinstance(frame, InputAudioRawFrame):
            if data.source is self._audio_source:
                if self.usage.answered_at is None:
                    self.usage.answered_at = time.monotonic()
                seconds = len(frame.audio) / (2 * frame.sample_rate)
                self.usage.caller_audio_s += seconds
                if (stt := self._listening()) is not None:
                    self.usage.meters[("stt", stt, "audio_seconds")] += seconds
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
        if isinstance(frame, VADUserStartedSpeakingFrame):
            self._caller_quiet_at = None
            return {}
        if isinstance(frame, VADUserStoppedSpeakingFrame):
            # The VAD only calls speech over after stop_secs of silence; the wait began then.
            self._caller_quiet_at = time.monotonic() - frame.stop_secs
            return {}
        if isinstance(frame, BotStartedSpeakingFrame) and self._caller_quiet_at is not None:
            waited = time.monotonic() - self._caller_quiet_at
            self.usage.response_ms.append(round(waited * 1000))
            self._caller_quiet_at = None
        if type(frame) in _STATES:
            return {"type": _STATES[type(frame)]}
        if isinstance(frame, TranscriptionFrame):
            return {"type": "user_transcript", "text": frame.text}
        if isinstance(frame, TTSTextFrame):
            return {"type": "bot_text", "text": frame.text}
        if isinstance(frame, MetricsFrame):
            for item in frame.data:
                named = self._vendor_of(item.processor)
                if isinstance(item, LLMUsageMetricsData):
                    self.usage.llm_prompt_tokens += item.value.prompt_tokens
                    self.usage.llm_completion_tokens += item.value.completion_tokens
                    if named:
                        self.usage.meters[(*named, "input_tokens")] += item.value.prompt_tokens
                        out = item.value.completion_tokens
                        self.usage.meters[(*named, "output_tokens")] += out
                elif isinstance(item, TTFBMetricsData) and named and item.value > 0:
                    self.usage.ttfb_ms.setdefault(named[0], []).append(round(item.value * 1000))
                elif isinstance(item, TTSUsageMetricsData):
                    self.usage.tts_characters += item.value
                    if named:
                        self.usage.meters[(*named, "characters")] += item.value
            return {}
        return None
