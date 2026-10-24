import asyncio
import base64
import json
import math
import struct
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from typing import Any, cast

from pipecat.audio.utils import create_stream_resampler, pcm_to_ulaw
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    InputAudioRawFrame,
    InputTransportMessageFrame,
    InterruptionFrame,
    TTSAudioRawFrame,
)
from pipecat.processors.frame_processor import FrameProcessorSetup

from engine.vobiz import StreamStart, VobizFrameSerializer, answer_xml, checkpoint

STREAM_ID = "b8f6c1e2-stream"
# Message shapes as documented by Vobiz (xml/stream/stream-events).
START: dict[str, Any] = {
    "event": "start",
    "sequenceNumber": 0,
    "start": {
        "streamId": STREAM_ID,
        "callId": "4c1d2e3f-call",
        "accountId": "MA_TEST",
        "tracks": ["inbound"],
        "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000},
    },
}


def _tone(rate: int, ms: int = 20) -> bytes:
    n = rate * ms // 1000
    return b"".join(
        struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate))) for i in range(n)
    )


def _media(payload: bytes) -> str:
    return json.dumps(
        {
            "event": "media",
            "sequenceNumber": 1,
            "streamId": STREAM_ID,
            "media": {
                "track": "inbound",
                "timestamp": "20",
                "chunk": 1,
                "payload": base64.b64encode(payload).decode(),
            },
        }
    )


def _serializer(start: dict[str, Any] = START, **kwargs: Any) -> VobizFrameSerializer:
    serializer = VobizFrameSerializer(StreamStart.parse(start), **kwargs)
    setup = cast(FrameProcessorSetup, SimpleNamespace(audio_in_sample_rate=16000))
    asyncio.run(serializer.setup(setup))
    return serializer


def _out(serializer: VobizFrameSerializer, frame: Any) -> dict[str, Any] | None:
    data = asyncio.run(serializer.serialize(frame))
    return None if data is None else cast(dict[str, Any], json.loads(data))


def test_start_ids_are_read_from_the_nested_start_object() -> None:
    start = StreamStart.parse(START)
    assert (start.stream_id, start.call_id) == (STREAM_ID, "4c1d2e3f-call")
    assert (start.encoding, start.sample_rate) == ("audio/x-mulaw", 8000)


def _feed(
    serializer: VobizFrameSerializer, payload: bytes, n: int = 25
) -> list[InputAudioRawFrame]:
    frames = [asyncio.run(serializer.deserialize(_media(payload))) for _ in range(n)]
    return [f for f in frames if isinstance(f, InputAudioRawFrame)]


def test_mulaw_media_becomes_pipeline_rate_pcm() -> None:
    ulaw = asyncio.run(pcm_to_ulaw(_tone(8000), 8000, 8000, create_stream_resampler()))
    assert len(ulaw) == 160  # 20 ms of 8 kHz mu-law
    frames = _feed(_serializer(), ulaw)
    assert {(f.sample_rate, f.num_channels) for f in frames} == {(16000, 1)}
    # 25 x 20 ms = 500 ms = 16000 bytes at 16 kHz 16-bit; the streaming resampler holds back
    # a few ms at the start.
    assert 15000 <= sum(len(f.audio) for f in frames) <= 16000


def test_l16_media_is_decoded_when_the_stream_reports_it() -> None:
    start = json.loads(json.dumps(START))
    start["start"]["mediaFormat"] = {"encoding": "audio/x-l16", "sampleRate": 16000}
    frames = _feed(_serializer(start), _tone(16000))
    assert 15000 <= sum(len(f.audio) for f in frames) <= 16000


def test_tts_audio_becomes_playaudio_mulaw_8k_with_matching_byte_count() -> None:
    serializer = _serializer()
    frame = TTSAudioRawFrame(audio=_tone(16000, ms=100), sample_rate=16000, num_channels=1)
    messages = [m for m in (_out(serializer, frame) for _ in range(5)) if m]
    assert messages
    for message in messages:
        assert message["event"] == "playAudio"
        assert message["streamId"] == STREAM_ID
        assert message["media"]["contentType"] == "audio/x-mulaw"
        assert message["media"]["sampleRate"] == 8000
    payload = b"".join(base64.b64decode(m["media"]["payload"]) for m in messages)
    assert 3700 <= len(payload) <= 4000  # 500 ms at 8000 one-byte samples, minus resampler lag


def test_interruption_sends_clear_audio_for_barge_in() -> None:
    assert _out(_serializer(), InterruptionFrame()) == {
        "event": "clearAudio",
        "streamId": STREAM_ID,
    }


def test_checkpoint_carries_stream_id_and_name() -> None:
    message = _out(_serializer(), checkpoint("utt-1"))
    assert message == {"event": "checkpoint", "streamId": STREAM_ID, "name": "utt-1"}


def test_played_stream_and_cleared_audio_acks_reach_the_pipeline() -> None:
    serializer = _serializer()
    played = asyncio.run(
        serializer.deserialize(json.dumps({"event": "playedStream", "name": "u1"}))
    )
    cleared = asyncio.run(
        serializer.deserialize(
            json.dumps({"event": "clearedAudio", "streamId": STREAM_ID, "sequenceNumber": 9})
        )
    )
    assert isinstance(played, InputTransportMessageFrame)
    assert played.message == {"event": "playedStream", "name": "u1"}
    assert isinstance(cleared, InputTransportMessageFrame)


def test_garbage_and_unknown_events_are_dropped() -> None:
    serializer = _serializer()
    assert asyncio.run(serializer.deserialize("not json")) is None
    assert asyncio.run(serializer.deserialize(json.dumps({"event": "mystery"}))) is None


def test_end_and_cancel_hang_up_exactly_once() -> None:
    calls: list[str] = []

    async def hang_up() -> None:
        calls.append("hangup")

    serializer = _serializer(hang_up=hang_up)
    assert _out(serializer, EndFrame()) is None
    assert _out(serializer, CancelFrame()) is None
    assert calls == ["hangup"]


def test_answer_xml_streams_both_ways_and_keeps_the_call_alive() -> None:
    xml = answer_xml("wss://engine.example.in/vobiz/stream?lang=te&x=1", "https://cb.example.in/s")
    stream = ET.fromstring(xml).find("Stream")
    assert stream is not None
    assert stream.text == "wss://engine.example.in/vobiz/stream?lang=te&x=1"
    assert stream.attrib == {
        "bidirectional": "true",
        "keepCallAlive": "true",
        "contentType": "audio/x-mulaw;rate=8000",
        "statusCallbackUrl": "https://cb.example.in/s",
    }
