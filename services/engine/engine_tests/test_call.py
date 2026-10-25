"""A whole call through the real engine app, stream WebSocket, Vobiz serializer, VAD, Smart Turn
and transport. Only the AI legs and the carrier are stand-ins (test-only adapters registered for
the duration of a test); B3 brings the real speech and LLM adapters."""

import base64
import json
import time
from collections.abc import Iterator, Mapping
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient
from pipecat.frames.frames import Frame, InputAudioRawFrame, TTSAudioRawFrame, TTSStoppedFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from starlette.websockets import WebSocketDisconnect

import engine.call
import engine.main
from app.providers import registry
from app.providers.base import Provider, ProviderKind, TelephonyProvider
from engine.call import CallSettings
from engine.main import app
from engine.services import SERVICES

from .test_vobiz import START, STREAM_ID

SILENCE_ULAW = base64.b64encode(b"\xff" * 160).decode()  # 20 ms of mu-law silence


class _Passthrough(FrameProcessor):
    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)


class _SpeaksOnce(_Passthrough):
    """Stands in for STT+LLM+TTS: the first caller audio makes the bot say 300 ms of tone."""

    spoke = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame) and not self.spoke:
            self.spoke = True
            tone = bytes([0, 40]) * (16000 * 3 // 10)
            await self.push_frame(TTSAudioRawFrame(audio=tone, sample_rate=16000, num_channels=1))
            await self.push_frame(TTSStoppedFrame())


def _leg(kind: ProviderKind) -> type[Provider]:
    class Leg(Provider):
        name = "testleg"

        async def health(self) -> None:
            return None

    Leg.kind = kind
    return Leg


class _Carrier(TelephonyProvider):
    name = "testcarrier"
    live = True
    failures = 0  # hang-ups to fail before succeeding
    hangups: ClassVar[list[str]] = []

    async def health(self) -> None:
        return None

    async def originate(
        self, from_number: str, to_number: str, answer_url: str, hangup_url: str | None = None
    ) -> str:
        return "test-call"

    def callback_is_authentic(self, url: str, headers: Mapping[str, str]) -> bool:
        return True

    async def call_detail(self, call_uuid: str) -> None:
        return None

    async def is_live(self, call_uuid: str) -> bool:
        return self.live

    async def hang_up(self, call_uuid: str) -> None:
        if _Carrier.failures:
            _Carrier.failures -= 1
            raise RuntimeError("carrier said 500")
        self.hangups.append(call_uuid)


@pytest.fixture
def events(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    published: list[dict[str, Any]] = []

    def sink(_redis: Any, _call_id: str) -> Any:
        async def publish(event: dict[str, Any]) -> None:
            published.append(event)

        return publish

    monkeypatch.setattr(engine.main, "redis_sink", sink)
    return published


@pytest.fixture
def providers(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Every leg resolvable: test-only adapters plus keys for them."""
    services = {
        (ProviderKind.STT, "testleg"): lambda *_: _SpeaksOnce(),
        (ProviderKind.LLM, "testleg"): lambda *_: _Passthrough(),
        (ProviderKind.TTS, "testleg"): lambda *_: _Passthrough(),
    }
    adapters = {
        **{key: _leg(key[0]) for key in services},
        (ProviderKind.TELEPHONY, "testcarrier"): _Carrier,
    }
    for key, factory in services.items():
        monkeypatch.setitem(SERVICES, key, factory)
    for kind, name in adapters:
        monkeypatch.setitem(registry.VENDOR_KEYS[kind], name, ())
        monkeypatch.setitem(registry.ADAPTERS, (kind, name), adapters[(kind, name)])
        monkeypatch.setenv(f"AXON_{kind.upper()}_PROVIDER", name)
    monkeypatch.setenv("AXON_ENGINE_PUBLIC_URL", "https://engine.example.in")
    monkeypatch.setattr(engine.call, "MIN_CALL_S", 0)
    _Carrier.live, _Carrier.failures, _Carrier.hangups = True, 0, []
    yield


def _call(
    monkeypatch: pytest.MonkeyPatch, events: list[dict[str, Any]], **settings: Any
) -> list[dict[str, Any]]:
    """Dial in, stream 1 s of silence, collect what the engine sends until it hangs up."""
    monkeypatch.setattr(
        engine.main, "CallSettings", lambda language: CallSettings(language=language, **settings)
    )
    sent: list[dict[str, Any]] = []
    with TestClient(app) as client, client.websocket_connect("/vobiz/stream?lang=te") as ws:
        ws.send_text(json.dumps(START))
        for _ in range(50):
            ws.send_text(json.dumps({"event": "media", "media": {"payload": SILENCE_ULAW}}))
        try:
            while True:
                sent.append(json.loads(ws.receive_text()))
        except WebSocketDisconnect:
            pass
        # The server finishes the call (recording, usage, `ended`) after closing the socket.
        deadline = time.monotonic() + 10
        while not (events and events[-1]["type"] == "ended") and time.monotonic() < deadline:
            time.sleep(0.05)
    return sent


def _types(events: list[dict[str, Any]]) -> list[str]:
    return [e["type"] for e in events]


def test_call_runs_end_to_end_and_the_length_cap_hangs_up(
    providers: None, events: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = _call(monkeypatch, events, max_call_s=2.0, silence_timeout_s=60.0)

    played = [m for m in sent if m["event"] == "playAudio"]
    assert played and {m["streamId"] for m in played} == {STREAM_ID}
    assert {m["media"]["contentType"] for m in played} == {"audio/x-mulaw"}
    assert {"event": "checkpoint", "streamId": STREAM_ID, "name": "utt-1"} in sent
    assert _Carrier.hangups == [START["start"]["callId"]]

    types = _types(events)
    assert types[0] == "started"
    assert "bot_started_speaking" in types and "bot_stopped_speaking" in types
    assert events[-1] == {"type": "ended", "reason": "max_length"}
    usage = next(e for e in events if e["type"] == "usage")
    assert 0.9 <= usage["caller_audio_s"] <= 1.05  # 50 x 20 ms in
    assert 1.5 <= usage["duration_s"] <= 4.0
    assert next(e for e in events if e["type"] == "recording_not_stored")


def test_silence_after_the_bot_speaks_ends_the_call(
    providers: None, events: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    _call(monkeypatch, events, max_call_s=30.0, silence_timeout_s=1.0)
    assert events[-1] == {"type": "ended", "reason": "silence"}
    assert len(_Carrier.hangups) == 1


def test_stream_for_a_call_the_carrier_does_not_have_is_refused(
    providers: None, events: list[dict[str, Any]]
) -> None:
    _Carrier.live = False
    with TestClient(app) as client, client.websocket_connect("/vobiz/stream") as ws:
        ws.send_text(json.dumps(START))
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert closed.value.code == 1008
    assert events == []


def test_answer_returns_stream_xml_when_every_leg_is_ready(providers: None) -> None:
    with TestClient(app) as client:
        response = client.post("/vobiz/answer?lang=hi")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert "wss://engine.example.in/vobiz/stream?lang=hi&amp;call=</Stream>" in response.text


def test_without_providers_answer_is_503_and_stream_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("SARVAM_API_KEY", "AXON_STT_PROVIDER", "AXON_LLM_PROVIDER", "AXON_TTS_PROVIDER"):
        monkeypatch.delenv(key, raising=False)
    with TestClient(app) as client:
        response = client.post("/vobiz/answer")
        with client.websocket_connect("/vobiz/stream") as ws:
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_text()
    assert response.status_code == 503
    assert response.json()["error"] == "provider_not_configured"
    assert response.json()["missing_keys"] == ["SARVAM_API_KEY"]
    assert closed.value.code == 1011


def test_public_url_is_required_to_answer(providers: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AXON_ENGINE_PUBLIC_URL")
    with TestClient(app) as client:
        response = client.post("/vobiz/answer")
    assert response.status_code == 503
    assert response.json()["missing_keys"] == ["AXON_ENGINE_PUBLIC_URL"]


def test_a_failed_hang_up_is_retried_once(
    providers: None, events: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    _Carrier.failures = 1
    _call(monkeypatch, events, max_call_s=2.0, silence_timeout_s=60.0)
    assert _Carrier.hangups == [START["start"]["callId"]]


def test_caller_hanging_up_ends_the_call(
    providers: None, events: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        engine.main, "CallSettings", lambda language: CallSettings(language=language)
    )
    with TestClient(app) as client:
        with client.websocket_connect("/vobiz/stream") as ws:
            ws.send_text(json.dumps(START))
            for _ in range(10):
                ws.send_text(json.dumps({"event": "media", "media": {"payload": SILENCE_ULAW}}))
        # leaving the block closes the socket, as Vobiz does when the caller hangs up
        deadline = time.monotonic() + 10
        while not (events and events[-1]["type"] == "ended") and time.monotonic() < deadline:
            time.sleep(0.05)
    assert events[-1] == {"type": "ended", "reason": "caller_hung_up"}


@pytest.mark.parametrize("first", [None, "not json", json.dumps({"event": "start"})])
def test_a_stream_without_a_valid_start_is_closed(
    providers: None, monkeypatch: pytest.MonkeyPatch, first: str | None
) -> None:
    monkeypatch.setattr(engine.main, "START_TIMEOUT_S", 0.3)
    with TestClient(app) as client, client.websocket_connect("/vobiz/stream") as ws:
        if first is not None:
            ws.send_text(first)
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    assert closed.value.code == 1008
