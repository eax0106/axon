"""Vobiz bidirectional audio stream: answer XML and the WebSocket frame serializer.

Protocol (Vobiz docs, xml/stream/stream-events):
  Vobiz -> us: `start` (ids nested in `start`), `media` (base64 audio), `playedStream`
               (checkpoint reached, matched by `name`), `clearedAudio` (flush done).
               No inbound `stop`: the socket closing is the end of the stream.
  us -> Vobiz: `playAudio` {streamId, media: {contentType, sampleRate, payload}},
               `checkpoint` {streamId, name}, `clearAudio` {streamId}, `stop` {streamId}.

We ask for and send mu-law 8 kHz: the phone leg is 8 kHz anyway, and mu-law avoids the
L16 byte-order ambiguity the Vobiz docs warn about. Inbound L16 is still decoded if a
stream reports it, as little-endian.
"""

import base64
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from xml.sax.saxutils import escape, quoteattr

from loguru import logger
from pipecat.audio.utils import create_stream_resampler, pcm_to_ulaw, ulaw_to_pcm
from pipecat.frames.frames import (
    AudioRawFrame,
    CancelFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    InputTransportMessageFrame,
    InterruptionFrame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
)
from pipecat.processors.frame_processor import FrameProcessorSetup
from pipecat.serializers.base_serializer import FrameSerializer

VOBIZ_RATE = 8000
INBOUND_CONTENT_TYPE = "audio/x-mulaw;rate=8000"


def answer_xml(stream_url: str, status_callback_url: str | None = None) -> str:
    """VobizXML that connects the answered call to our engine WebSocket.

    keepCallAlive keeps the call up after the stream starts (otherwise Vobiz reaches the
    end of the XML and hangs up).
    """
    callback = f" statusCallbackUrl={quoteattr(status_callback_url)}" if status_callback_url else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>"
        f'<Stream bidirectional="true" keepCallAlive="true" '
        f'contentType="{INBOUND_CONTENT_TYPE}"{callback}>{escape(stream_url)}</Stream>'
        "</Response>"
    )


@dataclass(frozen=True)
class StreamStart:
    stream_id: str
    call_id: str
    encoding: str
    sample_rate: int

    @classmethod
    def parse(cls, message: dict[str, Any]) -> "StreamStart":
        start = message["start"]
        media_format = start.get("mediaFormat") or {}
        return cls(
            stream_id=start["streamId"],
            call_id=start["callId"],
            encoding=str(media_format.get("encoding", INBOUND_CONTENT_TYPE)),
            sample_rate=int(media_format.get("sampleRate", VOBIZ_RATE)),
        )


def checkpoint(name: str) -> OutputTransportMessageFrame:
    """Frame that asks Vobiz to tell us (`playedStream`) when audio queued so far has played.

    Not urgent: it must queue behind the audio it marks the end of.
    """
    return OutputTransportMessageFrame(message={"event": "checkpoint", "name": name})


class VobizFrameSerializer(FrameSerializer):
    def __init__(
        self,
        start: StreamStart,
        hang_up: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        super().__init__(FrameSerializer.InputParams(resampler_clear_after_secs=None))
        self.start = start
        self._hang_up = hang_up
        self._hung_up = False
        self._pipeline_rate = 0
        self._in_resampler = create_stream_resampler()
        self._out_resampler = create_stream_resampler()

    async def setup(self, setup: FrameProcessorSetup) -> None:  # type: ignore[override]  # as Pipecat
        self._pipeline_rate = setup.audio_in_sample_rate

    def _event(self, event: str, **fields: Any) -> str:
        return json.dumps({"event": event, "streamId": self.start.stream_id, **fields})

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, (EndFrame, CancelFrame)):
            if self._hang_up and not self._hung_up:
                self._hung_up = True
                await self._hang_up()
            return None
        if isinstance(frame, InterruptionFrame):
            return self._event("clearAudio")
        if isinstance(frame, AudioRawFrame):
            ulaw = await pcm_to_ulaw(
                frame.audio, frame.sample_rate, VOBIZ_RATE, self._out_resampler
            )
            if not ulaw:
                return None
            media = {
                "contentType": "audio/x-mulaw",
                "sampleRate": VOBIZ_RATE,
                "payload": base64.b64encode(ulaw).decode("ascii"),
            }
            return self._event("playAudio", media=media)
        if isinstance(frame, (OutputTransportMessageFrame, OutputTransportMessageUrgentFrame)):
            if self.should_ignore_frame(frame):
                return None
            message = dict(frame.message)
            return self._event(message.pop("event"), **message)
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        try:
            message = json.loads(data)
        except json.JSONDecodeError:
            logger.warning("vobiz: non-JSON stream message dropped")
            return None
        event = message.get("event")
        if event == "media":
            payload = base64.b64decode(message.get("media", {}).get("payload") or "")
            pcm = await self._decode(payload) if payload else b""
            if not pcm:
                return None
            return InputAudioRawFrame(audio=pcm, sample_rate=self._pipeline_rate, num_channels=1)
        if event in ("playedStream", "clearedAudio"):
            return InputTransportMessageFrame(message=message)
        return None

    async def _decode(self, payload: bytes) -> bytes:
        if "mulaw" in self.start.encoding:
            pcm: bytes = await ulaw_to_pcm(
                payload, self.start.sample_rate, self._pipeline_rate, self._in_resampler
            )
            return pcm
        # audio/x-l16: signed 16-bit mono, little-endian (see module docstring).
        resampled: bytes = await self._in_resampler.resample(
            payload, self.start.sample_rate, self._pipeline_rate
        )
        return resampled
