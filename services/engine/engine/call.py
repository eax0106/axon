"""One phone call: a Pipecat pipeline from the Vobiz stream through STT, LLM and TTS and back.

    caller audio -> VAD + Smart Turn v3 -> STT -> LLM -> TTS (sentence by sentence) -> caller
                                                                   \\-> recorder (2 tracks)

Barge-in: when the caller starts talking over the bot, Pipecat interrupts the bot and the
serializer sends Vobiz `clearAudio`, which drops audio already queued at the carrier.
"""

import asyncio
import io
import time
import wave
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from loguru import logger
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import EndFrame, Frame, TTSStoppedFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import (
    TurnAnalyzerUserTurnStopStrategy,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from starlette.websockets import WebSocket, WebSocketState

from app.providers.base import ObjectStorageProvider, ProviderKind, ProviderNotConfiguredError
from app.providers.registry import require
from engine.events import CallObserver, EventSink, Usage
from engine.vobiz import StreamStart, VobizFrameSerializer, checkpoint

PIPELINE_RATE = 16000  # Smart Turn and Silero work at 16 kHz; the serializer converts to 8 kHz
MIN_CALL_S, MAX_CALL_S = 10, 3600


@dataclass(frozen=True)
class CallSettings:
    language: str = "en"
    system_prompt: str = ""  # compiled from the employee's script in B4
    max_call_s: float = 600.0  # account setting, 10 s to 60 min
    silence_timeout_s: float = 20.0  # caller silent this long after the bot spoke -> end call

    def __post_init__(self) -> None:
        if not MIN_CALL_S <= self.max_call_s <= MAX_CALL_S:
            raise ValueError(f"max_call_s must be {MIN_CALL_S}-{MAX_CALL_S}")


class UtteranceCheckpoints(FrameProcessor):
    """After each bot utterance, ask Vobiz to confirm (playedStream) when it finished playing."""

    def __init__(self) -> None:
        super().__init__()
        self._count = 0

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)
        if isinstance(frame, TTSStoppedFrame):
            self._count += 1
            await self.push_frame(checkpoint(f"utt-{self._count}"))


def _wav(audio: bytes, sample_rate: int, channels: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(audio)
    return buffer.getvalue()


async def store_recording(call_id: str, wav: bytes, publish: EventSink) -> None:
    key = f"recordings/{call_id}.wav"
    try:
        storage = require(ProviderKind.STORAGE)
    except ProviderNotConfiguredError as exc:
        await publish({"type": "recording_not_stored", "detail": exc.detail})
        return
    assert isinstance(storage, ObjectStorageProvider)
    await storage.put(key, wav, "audio/wav")
    await publish({"type": "recording_stored", "key": key})


async def run_call(
    websocket: WebSocket,
    start: StreamStart,
    legs: tuple[FrameProcessor, FrameProcessor, FrameProcessor],
    settings: CallSettings,
    publish: EventSink,
    hang_up: Callable[[], Awaitable[None]],
) -> Usage:
    """Run the call until it ends; return what it used. `websocket` has already read `start`."""
    transport = FastAPIWebsocketTransport(
        websocket,
        FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            serializer=VobizFrameSerializer(start, hang_up=hang_up),
        ),
    )
    stt, llm, tts = legs
    messages: list[Any] = (
        [{"role": "system", "content": settings.system_prompt}] if settings.system_prompt else []
    )
    aggregators = LLMContextAggregatorPair(
        LLMContext(messages=messages),
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
            user_turn_strategies=UserTurnStrategies(
                stop=[TurnAnalyzerUserTurnStopStrategy(turn_analyzer=LocalSmartTurnAnalyzerV3())]
            ),
            user_idle_timeout=settings.silence_timeout_s,
        ),
    )
    # Caller left, bot right, at the phone line's 8 kHz.
    # ponytail: buffers the whole call in RAM (32 KB/s, ~19 MB for a 10-min call); stream chunks
    # to storage with buffer_size if concurrent calls per engine make that matter.
    recorder = AudioBufferProcessor(sample_rate=8000, num_channels=2)
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            aggregators.user(),
            llm,
            tts,
            UtteranceCheckpoints(),
            transport.output(),
            recorder,
            aggregators.assistant(),
        ]
    )
    live = _LiveEvents(publish)
    observer = CallObserver(live.emit, transport.input())
    # ponytail: PipelineTask/PipelineRunner are deprecated in Pipecat 1.3 (removed in 2.0); the
    # PipelineWorker/WorkerRunner pair never returned after EndFrame here. Migrate with 2.0.
    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=PIPELINE_RATE,
            audio_out_sample_rate=PIPELINE_RATE,
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        observers=[observer],
        idle_timeout_secs=None,  # the silence watchdog and the length cap end calls instead
        enable_rtvi=False,
    )
    ended: list[str] = []
    recording: list[bytes] = []

    async def end(reason: str) -> None:
        if not ended:
            ended.append(reason)
            await task.queue_frame(EndFrame())

    @aggregators.user().event_handler("on_user_turn_idle")
    async def _silence(_: Any) -> None:
        await end("silence")

    @transport.event_handler("on_client_disconnected")
    async def _caller_gone(*_: Any) -> None:
        if not ended:
            ended.append("caller_hung_up")
        await task.cancel()

    @recorder.event_handler("on_audio_data")
    async def _recorded(_: Any, audio: bytes, sample_rate: int, channels: int) -> None:
        if audio:
            recording.append(_wav(audio, sample_rate, channels))

    await publish({"type": "started", "call_id": start.call_id, "language": settings.language})
    await recorder.start_recording()
    cap = asyncio.get_running_loop().call_later(
        settings.max_call_s, lambda: asyncio.ensure_future(end("max_length"))
    )
    error: BaseException | None = None
    try:
        await PipelineRunner(handle_sigint=False).run(task)
    except BaseException as exc:  # re-raised below, after the call is finished
        error = exc
        if not ended:
            caller_gone = websocket.client_state == WebSocketState.DISCONNECTED
            ended.append("caller_hung_up" if caller_gone else type(exc).__name__)
    finally:
        cap.cancel()
        observer.usage.ended_at = time.monotonic()
    reason = ended[0] if ended else "pipeline_finished"
    # However the pipeline exits, finish the call (recording, usage, `ended` last) in its own
    # task: if this handler is being cancelled, its cancel scope would interrupt every await here.
    finishing = asyncio.create_task(
        _finish(live, publish, start.call_id, recording, observer.usage, reason)
    )
    _FINISHING.add(finishing)
    finishing.add_done_callback(_FINISHING.discard)
    try:
        await asyncio.shield(finishing)
    finally:
        if error is not None:
            raise error
    return observer.usage


class _LiveEvents:
    """Gate for a call's live events: once closed, late pipeline events are dropped."""

    def __init__(self, publish: EventSink) -> None:
        self._publish = publish
        self._lock = asyncio.Lock()
        self._closed = False

    async def emit(self, event: dict[str, Any]) -> None:
        async with self._lock:
            if not self._closed:
                await self._publish(event)

    async def close(self) -> None:
        async with self._lock:  # waits for an in-flight emit to land first
            self._closed = True


_FINISHING: set[asyncio.Task[None]] = set()  # strong refs so finishing tasks aren't collected


async def _finish(
    live: "_LiveEvents",
    publish: EventSink,
    call_id: str,
    recording: list[bytes],
    usage: Usage,
    reason: str,
) -> None:
    # Pipeline tasks still tearing down may emit late events (e.g. bot_stopped_speaking); close the
    # live gate first so `ended` is always the last event.
    await live.close()
    if recording:
        try:
            await store_recording(call_id, recording[0], publish)
        except Exception:
            logger.exception("recording upload failed")
            await publish({"type": "recording_not_stored", "detail": "upload failed"})
    await publish(usage.as_event())
    await publish({"type": "ended", "reason": reason})
