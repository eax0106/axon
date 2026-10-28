"""Failing vendors for the failover tests: real Pipecat services pointed at local servers that
refuse them (401 on the websocket handshake or the HTTP request) or never answer, and stand-ins
for the vendors that work."""

import json
import threading
import time
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient
from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    LLMMessagesAppendFrame,
    LLMTextFrame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    TTSTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.smallest.stt import SmallestSTTService
from pipecat.transcriptions.language import Language
from starlette.websockets import WebSocketDisconnect

import engine.call
import engine.main
import engine.services
from app.models import VoiceTier
from app.providers import failover, registry
from app.providers.base import Provider, ProviderKind
from engine.call import CallSettings
from engine.main import app
from engine.services import SERVICES

from .test_call import SILENCE_ULAW, _Carrier
from .test_vobiz import START

REPLY = ["Hello", " there", "."]
LANGUAGE = Language.EN


class _Vendor(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # a websocket client needs an HTTP/1.1 answer to its upgrade
    modes: ClassVar[dict[int, str]] = {}
    requests: ClassVar[dict[int, int]] = {}

    def _mode(self) -> str:
        port = int(self.connection.getsockname()[1])
        _Vendor.requests[port] = _Vendor.requests.get(port, 0) + 1
        return _Vendor.modes[port]

    def _refuse(self) -> None:
        body = b'{"error": {"message": "invalid api key"}}'
        self.send_response(401)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # a websocket handshake
        if self._mode() == "hang":
            time.sleep(30)
            return
        self._refuse()

    def do_POST(self) -> None:  # an OpenAI-style chat completion
        self.rfile.read(int(self.headers.get("content-length", 0)))
        mode = self._mode()
        if mode == "refuse":
            self._refuse()
            return
        if mode == "hang":
            time.sleep(30)
            return
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("connection", "close")
        self.end_headers()
        for text in REPLY:
            self._event({"choices": [{"index": 0, "delta": {"content": text}}]})
        usage = {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15}
        self._event({"choices": [], "usage": usage})
        self.wfile.write(b"data: [DONE]\n\n")
        self.close_connection = True

    def _event(self, data: dict[str, Any]) -> None:
        chunk = {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "m", **data}
        self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
        self.wfile.flush()

    def log_message(self, *_: Any) -> None:
        return None


class Servers:
    """Local vendor servers, each in one mode: `refuse` (401), `hang` (never answers) or `ok`."""

    def __init__(self) -> None:
        self._servers: list[ThreadingHTTPServer] = []

    def start(self, mode: str) -> int:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Vendor)
        server.daemon_threads = True
        port = server.server_address[1]
        _Vendor.modes[port] = mode
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self._servers.append(server)
        return port

    def http(self, mode: str) -> str:
        return f"http://127.0.0.1:{self.start(mode)}/v1"

    def ws(self, mode: str) -> str:
        return f"ws://127.0.0.1:{self.start(mode)}"

    @staticmethod
    def hits(url: str) -> int:
        port = int(url.split(":")[2].split("/")[0])
        return _Vendor.requests.get(port, 0)

    def close(self) -> None:
        for server in self._servers:
            server.shutdown()
            server.server_close()


class Listener(FrameProcessor):
    """A working speech-to-text: the caller's first audio becomes the words "hello"."""

    heard: ClassVar[list[str]] = []

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame) and not Listener.heard:
            Listener.heard.append("hello")
            said: list[Any] = [{"role": "user", "content": "hello"}]
            await self.push_frame(LLMMessagesAppendFrame(said, run_llm=True))


class Speaker(FrameProcessor):
    """A working text-to-speech: every piece of text becomes 100 ms of tone, and is noted."""

    said: ClassVar[list[str]] = []

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        text = frame.text if isinstance(frame, LLMTextFrame | TTSSpeakFrame) else None
        if text is None:
            await self.push_frame(frame, direction)
            return
        Speaker.said.append(text)
        tone = bytes([0, 40]) * 1600
        await self.push_frame(TTSStartedFrame())
        await self.push_frame(TTSAudioRawFrame(audio=tone, sample_rate=16000, num_channels=1))
        await self.push_frame(TTSTextFrame(text, text_type="sentence"))
        await self.push_frame(TTSStoppedFrame())


def _adapter(kind: ProviderKind, name: str) -> type[Provider]:
    class Adapter(Provider):
        async def health(self) -> None:
            return None

    Adapter.kind, Adapter.name = kind, name
    return Adapter


@pytest.fixture
def vendors() -> Iterator[Servers]:
    running = Servers()
    yield running
    running.close()


@pytest.fixture
def wire(
    monkeypatch: pytest.MonkeyPatch, no_keys: None, vendors: Servers
) -> Callable[..., dict[str, str]]:
    """Register the vendors of one test, the failing ones first. Returns their addresses."""

    def wire(
        llm: str = "refuse", backups: tuple[str, ...] = ("stt", "llm", "tts"), **settings: Any
    ) -> dict[str, str]:
        urls = {
            "stt": vendors.ws("refuse"),
            "tts": vendors.ws("refuse"),
            "badllm": vendors.http(llm),
            "goodllm": vendors.http("ok"),
        }

        def llm_at(url: str) -> Callable[..., FrameProcessor]:
            return lambda *_: engine.services._SarvamLLM(
                api_key="k",
                base_url=url,
                settings=engine.services._SarvamLLM.Settings(model="sarvam-105b"),
            )

        services: dict[tuple[ProviderKind, str], Callable[..., FrameProcessor]] = {
            (ProviderKind.STT, "badstt"): lambda *_: SmallestSTTService(
                api_key="k",
                base_url=urls["stt"],
                settings=SmallestSTTService.Settings(language=LANGUAGE),
            ),
            (ProviderKind.STT, "goodstt"): lambda *_: Listener(),
            (ProviderKind.LLM, "badllm"): llm_at(urls["badllm"]),
            (ProviderKind.LLM, "goodllm"): llm_at(urls["goodllm"]),
            (ProviderKind.TTS, "badtts"): lambda *_: CartesiaTTSService(
                api_key="k",
                url=urls["tts"] + "/tts/websocket",
                settings=CartesiaTTSService.Settings(voice="v", language=LANGUAGE),
            ),
            (ProviderKind.TTS, "goodtts"): lambda *_: Speaker(),
        }
        for (kind, name), factory in services.items():
            if name.startswith("good") and str(kind) not in backups:
                continue
            monkeypatch.setitem(SERVICES, (kind, name), factory)
            monkeypatch.setitem(registry.VENDOR_KEYS[kind], name, ())
            monkeypatch.setitem(registry.ADAPTERS, (kind, name), _adapter(kind, name))
        for leg in ("stt", "llm", "tts"):
            monkeypatch.setenv(f"AXON_{leg.upper()}_PROVIDER", f"bad{leg}")
        # The voice chain falls back to the Value vendor: here, the working stand-in.
        monkeypatch.setitem(registry.TIER_TTS, VoiceTier.VALUE, "goodtts")
        monkeypatch.setitem(failover.TTS_TIER, "goodtts", VoiceTier.VALUE)
        monkeypatch.setitem(failover.TTS_TIER, "badtts", VoiceTier.PREMIUM)
        carrier = (ProviderKind.TELEPHONY, "testcarrier")
        monkeypatch.setitem(registry.VENDOR_KEYS[ProviderKind.TELEPHONY], "testcarrier", ())
        monkeypatch.setitem(registry.ADAPTERS, carrier, _Carrier)
        monkeypatch.setenv("AXON_TELEPHONY_PROVIDER", "testcarrier")
        monkeypatch.setenv("AXON_ENGINE_PUBLIC_URL", "https://engine.example.in")
        monkeypatch.setattr(engine.call, "MIN_CALL_S", 0)
        monkeypatch.setattr(
            engine.main,
            "CallSettings",
            lambda language: CallSettings(
                language=language, max_call_s=6.0, silence_timeout_s=60.0, **settings
            ),
        )
        _Carrier.live, _Carrier.failures, _Carrier.hangups = True, 0, []
        Listener.heard, Speaker.said = [], []
        return urls

    return wire


def call(events: list[dict[str, Any]], query: str = "") -> list[dict[str, Any]]:
    """Dial in, stream a second of silence, confirm what is played (as Vobiz does), and wait for
    the call to finish and be recorded."""
    sent: list[dict[str, Any]] = []
    with TestClient(app) as client, client.websocket_connect(f"/vobiz/stream{query}") as ws:
        ws.send_text(json.dumps(START))
        for _ in range(50):
            ws.send_text(json.dumps({"event": "media", "media": {"payload": SILENCE_ULAW}}))
        try:
            while True:
                sent.append(json.loads(ws.receive_text()))
                if sent[-1]["event"] == "checkpoint":  # the carrier played what came before it
                    name = sent[-1]["name"]
                    ws.send_text(json.dumps({"event": "playedStream", "name": name}))
        except WebSocketDisconnect:
            pass
        deadline = time.monotonic() + 15
        while not (events and events[-1]["type"] == "ended") and time.monotonic() < deadline:
            time.sleep(0.05)
        time.sleep(0.5)  # the call's row is written just after the last live event
    return sent


def switches(events: list[dict[str, Any]]) -> dict[str, tuple[str, str]]:
    return {e["leg"]: (e["from"], e["to"]) for e in events if e["type"] == "failover"}
