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
from pipecat.adapters.llm.schemas.function_schema import FunctionSchema
from pipecat.adapters.llm.schemas.tools_schema import ToolsSchema
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    EndFrame,
    Frame,
    FunctionCallResultProperties,
    LLMMessagesAppendFrame,
    LLMRunFrame,
    TTSSpeakFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
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
from pipecat.serializers.base_serializer import FrameSerializer
from pipecat.services.llm_service import FunctionCallParams
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from pipecat.turns.user_mute import MuteUntilFirstBotCompleteUserMuteStrategy
from pipecat.turns.user_stop.turn_analyzer_user_turn_stop_strategy import (
    TurnAnalyzerUserTurnStopStrategy,
)
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from starlette.websockets import WebSocket, WebSocketState

from app.actions.tools import Tool, run_timed
from app.models import VoiceTier
from app.providers.base import ObjectStorageProvider, ProviderKind, ProviderNotConfiguredError
from app.providers.failover import billed_tier
from app.providers.registry import require
from engine.ambience import mixer_for
from engine.events import CallObserver, EventSink, Usage
from engine.goodbye import GoodbyeGate, PlayedStreamTap
from engine.legs import ServiceLeg
from engine.records import PROVIDER_FAILURE, CallRecorder
from engine.vobiz import checkpoint

PIPELINE_RATE = 16000  # Smart Turn and Silero work at 16 kHz; the serializer converts to 8 kHz
MIN_CALL_S, MAX_CALL_S = 10, 3600
NO_REPLY = FunctionCallResultProperties(run_llm=False)
# Spoken when a leg of the call has no vendor left, before the call is hung up. Our own words;
# the Telugu and Hindi wait for the native-speaker check (WIRING_CHECKLIST).
APOLOGY = {
    "en": "Sorry, we have a technical problem and need to end this call here. Thank you.",
    "hi": "माफ़ कीजिए, तकनीकी समस्या की वजह से हमें यह कॉल यहीं खत्म करनी होगी। धन्यवाद।",
    "te": "క్షమించండి, సాంకేతిక సమస్య వల్ల ఈ కాల్‌ను ఇక్కడితో ముగించాల్సి వస్తోంది. ధన్యవాదాలు.",
}


@dataclass(frozen=True)
class CallSettings:
    language: str = "en"
    system_prompt: str = ""  # compiled from the employee's script (app.employees.compiler)
    ambience: str = "none"
    voice_tier: str | None = None  # recorded on the call: it decides the price per minute
    ambience_volume: float = 0.3
    max_call_s: float = 600.0  # account setting, 10 s to 60 min
    silence_timeout_s: float = 20.0  # caller silent this long after the bot spoke -> end call
    opening: str = ""  # spoken first, before the caller says a word (an incoming call)
    transfer_to: str | None = None  # a person the AI may hand the call to (an incoming call)
    tools: tuple[Tool, ...] = ()  # what the employee's actions let the AI do during the call

    def __post_init__(self) -> None:
        if not MIN_CALL_S <= self.max_call_s <= MAX_CALL_S:
            raise ValueError(f"max_call_s must be {MIN_CALL_S}-{MAX_CALL_S}")


class UtteranceCheckpoints(FrameProcessor):
    """After each bot utterance, ask Vobiz to confirm (playedStream) when it finished playing.
    The goodbye gate learns from here which utterances are still in flight."""

    def __init__(self, gate: GoodbyeGate) -> None:
        super().__init__()
        self._count = 0
        self._gate = gate

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSStartedFrame):
            self._gate.tts_started()
        await self.push_frame(frame, direction)
        if isinstance(frame, TTSStoppedFrame):
            self._count += 1
            name = f"utt-{self._count}"
            self._gate.checkpoint_issued(name)
            await self.push_frame(checkpoint(name))
            self._gate.tts_stopped()


def _wav(audio: bytes, sample_rate: int, channels: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(audio)
    return buffer.getvalue()


async def store_recording(call_id: str, wav: bytes, publish: EventSink) -> str | None:
    """Upload the recording; returns its storage key, or None when it could not be stored."""
    key = f"recordings/{call_id}.wav"
    try:
        storage = require(ProviderKind.STORAGE)
    except ProviderNotConfiguredError as exc:
        await publish({"type": "recording_not_stored", "detail": exc.detail})
        return None
    assert isinstance(storage, ObjectStorageProvider)
    await storage.put(key, wav, "audio/wav")
    await publish({"type": "recording_stored", "key": key})
    return key


END_CALL = FunctionSchema(
    name="end_call",
    description=(
        "Hang up. Call it right after your goodbye, once an end rule says the call is over."
    ),
    properties={},
    required=[],
)


TRANSFER_TO_HUMAN = FunctionSchema(
    name="transfer_to_human",
    description=(
        "Connect the caller to a person. Say you are connecting them first, then call this."
    ),
    properties={},
    required=[],
)
TRANSFER_FAILED = (
    "The transfer did not go through. Apologise in one sentence, say you could not connect them, "
    "and offer to take a message instead."
)


def register_end_call(llm: FrameProcessor, gate: GoodbyeGate) -> None:
    """Let the LLM end the call. (A leg without function calling cannot, and that is fine.)"""
    register = getattr(llm, "register_function", None)
    if register is None:
        return

    async def end_call(params: FunctionCallParams) -> None:
        await gate.request_end()
        # The goodbye was already spoken; do not ask the LLM for another turn.
        await params.result_callback({"status": "ending"}, properties=NO_REPLY)

    register("end_call", end_call)


def register_tools(
    llm: FrameProcessor, tools: tuple[Tool, ...], emit: Callable[[dict[str, Any]], Awaitable[None]]
) -> None:
    """Let the LLM use the employee's actions. A write must not be abandoned halfway because the
    caller spoke over the AI, so an interruption does not cancel a tool. Only the fact that a tool
    ran is recorded: never what it was given or answered, which can be a caller's details."""
    register = getattr(llm, "register_function", None)
    if register is None:
        return
    for tool in tools:

        async def use(params: FunctionCallParams, tool: Tool = tool) -> None:
            result, ms = await run_timed(tool, dict(params.arguments))
            await emit(
                {"type": "action", "name": tool.name, "ok": bool(result.get("ok")), "ms": ms}
            )
            await params.result_callback(result)

        register(tool.name, use, cancel_on_interruption=False, timeout_secs=tool.timeout_s + 10)


async def run_call(
    websocket: WebSocket,
    call_id: str,
    serializer: FrameSerializer,
    legs: tuple[FrameProcessor, FrameProcessor, FrameProcessor],
    settings: CallSettings,
    publish: EventSink,
    call_record: CallRecorder | None = None,
    carrier_call_id: str | None = None,
    transfer: Callable[[], Awaitable[None]] | None = None,
) -> Usage:
    """Run the call until it ends; return what it used. The caller has already accepted the
    WebSocket and read any handshake; `serializer` speaks the stream protocol."""
    transport = FastAPIWebsocketTransport(
        websocket,
        FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            serializer=serializer,
            audio_out_mixer=mixer_for(settings.ambience, settings.ambience_volume),
        ),
    )
    stt, llm, tts = legs
    messages: list[Any] = (
        [{"role": "system", "content": settings.system_prompt}] if settings.system_prompt else []
    )
    ended: list[str] = []
    recording: list[bytes] = []

    async def end(reason: str) -> None:
        if not ended:
            ended.append(reason)
            await task.queue_frame(EndFrame())

    gate = GoodbyeGate(end)
    register_end_call(llm, gate)
    tools = [END_CALL]
    if transfer is not None:
        tools.append(TRANSFER_TO_HUMAN)
    tools += [
        FunctionSchema(t.name, t.description, t.properties, t.required) for t in settings.tools
    ]
    aggregators = LLMContextAggregatorPair(
        LLMContext(messages=messages, tools=ToolsSchema(standard_tools=tools)),
        user_params=LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
            # The caller hears the whole opening (the recording notice) before being listened to.
            user_mute_strategies=(
                [MuteUntilFirstBotCompleteUserMuteStrategy()] if settings.opening else []
            ),
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
            PlayedStreamTap(gate),
            stt,
            aggregators.user(),
            llm,
            tts,
            UtteranceCheckpoints(gate),
            transport.output(),
            recorder,
            aggregators.assistant(),
        ]
    )
    live = _LiveEvents(publish, call_record)
    register_tools(llm, settings.tools, live.emit)
    switched = [leg for leg in legs if isinstance(leg, ServiceLeg)]
    names = {s.name: (str(leg.kind), v) for leg in switched for s, v in leg.vendors.items()}
    observer = CallObserver(
        live.emit,
        transport.input(),
        vendor_of=names.get,
        listening=lambda: stt.vendor if isinstance(stt, ServiceLeg) else None,
    )
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

    given_up: list[ProviderKind] = []
    tier = [VoiceTier(settings.voice_tier)] if settings.voice_tier else []

    async def failed_over(leg: ServiceLeg, failed: Any, now_on: Any, error: str) -> None:
        """The leg moved to its next vendor. A lost LLM turn is asked for again; a fallback voice
        of a cheaper tier sets what the call is billed at, for the rest of the call and before."""
        old, new = leg.vendors[failed], leg.vendors[now_on]
        await live.emit({"type": "failover", "leg": str(leg.kind), "from": old, "to": new})
        logger.warning(f"{leg.kind} failed over from {old} to {new}: {error}")
        if call_record is not None:
            await call_record.vendor_failed(str(leg.kind), old)
        if leg.kind is ProviderKind.LLM:
            await task.queue_frame(LLMRunFrame())
        cheaper = billed_tier([*tier, leg.tiers[now_on]])
        if tier and cheaper is not tier[0]:
            assert cheaper is not None
            tier[0] = cheaper
            await live.emit({"type": "tier_fallback", "tier": cheaper.value})
            if call_record is not None:
                await call_record.bill_at(cheaper.value)

    async def exhausted(leg: ServiceLeg, failed: Any, error: str) -> None:
        """The leg has no vendor left: apologise (if a voice still works) and hang up once it was
        heard, or hang up at once."""
        vendor = leg.vendors[failed]
        given_up.append(leg.kind)
        await live.emit({"type": "provider_failure", "leg": str(leg.kind), "vendor": vendor})
        logger.error(f"{leg.kind} has no vendor left ({vendor}: {error}); ending the call")
        if call_record is not None:
            await call_record.vendor_failed(str(leg.kind), vendor)
        if ProviderKind.TTS not in given_up and not ended:
            apology = TTSSpeakFrame(APOLOGY.get(settings.language, APOLOGY["en"]))
            apology.interruptible = False
            await task.queue_frame(apology)
            await gate.request_end(lambda: end(PROVIDER_FAILURE))
        else:
            await end(PROVIDER_FAILURE)

    def watch(leg: ServiceLeg) -> None:
        async def on_failover(_: Any, failed: Any, now_on: Any, error: str) -> None:
            await failed_over(leg, failed, now_on, error)

        async def on_exhausted(_: Any, failed: Any, error: str) -> None:
            await exhausted(leg, failed, error)

        leg.strategy.add_event_handler("on_failover", on_failover)
        leg.strategy.add_event_handler("on_exhausted", on_exhausted)

    for leg in switched:
        watch(leg)

    transferring: list[bool] = []

    async def hand_over() -> None:
        """Ask the carrier to move the caller to a person. The stream then closes by itself, and
        our end of it must not hang the call up."""
        assert transfer is not None
        transferring.append(True)  # the carrier may close the stream before its answer reaches us
        try:
            await transfer()
        except Exception:
            logger.exception("transfer failed")
            transferring.clear()
            gate.reopen()
            await task.queue_frame(
                LLMMessagesAppendFrame(
                    [{"role": "system", "content": TRANSFER_FAILED}], run_llm=True
                )
            )
            return
        keep_up = getattr(serializer, "keep_call_up", None)
        if keep_up is not None:
            keep_up()
        await live.emit({"type": "transferred"})
        await end("transferred")

    if transfer is not None:
        register = getattr(llm, "register_function", None)
        if register is not None:

            async def transfer_to_human(params: FunctionCallParams) -> None:
                await gate.request_end(hand_over)  # after what was said has been heard
                await params.result_callback({"status": "transferring"}, properties=NO_REPLY)

            register("transfer_to_human", transfer_to_human)

    @aggregators.user().event_handler("on_user_turn_idle")
    async def _silence(_: Any) -> None:
        await end("silence")

    @transport.event_handler("on_client_disconnected")
    async def _caller_gone(*_: Any) -> None:
        if not ended:
            ended.append("transferred" if transferring else "caller_hung_up")
        await task.cancel()

    @recorder.event_handler("on_audio_data")
    async def _recorded(_: Any, audio: bytes, sample_rate: int, channels: int) -> None:
        if audio:
            recording.append(_wav(audio, sample_rate, channels))

    if call_record is not None:
        await call_record.started(carrier_call_id, settings.voice_tier)
    await publish({"type": "started", "call_id": call_id, "language": settings.language})
    await recorder.start_recording()
    if settings.opening:
        # Fixed words, and not to be talked over: the caller hears the recording notice first.
        opening = TTSSpeakFrame(settings.opening)
        opening.interruptible = False
        await task.queue_frame(opening)
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
        gate.cancel()
        observer.usage.ended_at = time.monotonic()
    reason = ended[0] if ended else "pipeline_finished"
    # The vendors that carried the call to its end count as a success for their health score.
    served = {str(leg.kind): leg.vendor for leg in switched if leg.kind not in given_up}
    # However the pipeline exits, finish the call (recording, usage, `ended` last) in its own
    # task: if this handler is being cancelled, its cancel scope would interrupt every await here.
    finishing = asyncio.create_task(
        _finish(live, publish, call_id, recording, observer.usage, reason, call_record, served)
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

    def __init__(self, publish: EventSink, recorder: CallRecorder | None = None) -> None:
        self._publish = publish
        self._recorder = recorder
        self._lock = asyncio.Lock()
        self._closed = False

    async def emit(self, event: dict[str, Any]) -> None:
        async with self._lock:
            if not self._closed:
                if self._recorder is not None:
                    self._recorder.tap(event)
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
    recorder: CallRecorder | None,
    served: dict[str, str],
) -> None:
    # Pipeline tasks still tearing down may emit late events (e.g. bot_stopped_speaking); close the
    # live gate first so `ended` is always the last event.
    await live.close()

    async def emit(event: dict[str, Any]) -> None:
        if recorder is not None:
            recorder.tap(event)
        await publish(event)

    key: str | None = None
    if recording:
        try:
            key = await store_recording(call_id, recording[0], emit)
        except Exception:
            logger.exception("recording upload failed")
            await emit({"type": "recording_not_stored", "detail": "upload failed"})
    await emit(usage.as_event())
    await emit({"type": "ended", "reason": reason})
    if recorder is not None:
        try:
            await recorder.finished(reason, key, served)
        except Exception:
            logger.exception("could not write the call record")
