"""Browser test call: the dashboard's audio WebSocket to the engine.

Protocol (JSON text frames; audio is base64 16-bit little-endian mono PCM at 16 kHz):
  browser -> engine: {"event": "media", "payload": "<b64>"}
                     {"event": "playedStream", "name": "<checkpoint>"}   (reply to a checkpoint)
  engine -> browser: {"event": "playAudio", "sampleRate": 16000, "payload": "<b64>"}
                     {"event": "clearAudio"}                              (caller barged in)
                     {"event": "checkpoint", "name": "utt-1"}             (reply with playedStream
                                                                          once that audio played)
The engine closes the socket when the call ends.
"""

import base64
import json
from typing import Any

from loguru import logger
from pipecat.frames.frames import (
    AudioRawFrame,
    Frame,
    InputAudioRawFrame,
    InputTransportMessageFrame,
    InterruptionFrame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
)
from pipecat.serializers.base_serializer import FrameSerializer

WEB_RATE = 16000


class WebFrameSerializer(FrameSerializer):
    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, InterruptionFrame):
            return json.dumps({"event": "clearAudio"})
        if isinstance(frame, AudioRawFrame):
            if frame.sample_rate != WEB_RATE or not frame.audio:
                return None
            payload = base64.b64encode(frame.audio).decode("ascii")
            return json.dumps({"event": "playAudio", "sampleRate": WEB_RATE, "payload": payload})
        if isinstance(frame, (OutputTransportMessageFrame, OutputTransportMessageUrgentFrame)):
            return json.dumps(frame.message)
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        try:
            message: dict[str, Any] = json.loads(data)
        except json.JSONDecodeError:
            logger.warning("web call: non-JSON message dropped")
            return None
        event = message.get("event")
        if event == "media":
            audio = base64.b64decode(message.get("payload") or "")
            if not audio:
                return None
            return InputAudioRawFrame(audio=audio, sample_rate=WEB_RATE, num_channels=1)
        if event == "playedStream":
            return InputTransportMessageFrame(message=message)
        return None
