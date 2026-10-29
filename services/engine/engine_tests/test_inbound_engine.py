"""An incoming call through the real engine app: the answer URL, the opening, the stream."""

import json
import time
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from pipecat.frames.frames import (
    Frame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    TTSTextFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from starlette.websockets import WebSocketDisconnect
from tests.conftest import sql
from tests.inbound_support import calls, inbound_employee

import engine.call
from app.providers.base import ProviderKind
from engine.main import app
from engine.services import SERVICES

from .test_call import (  # noqa: F401 - fixtures
    SILENCE_ULAW,
    _Carrier,
    _Passthrough,
    events,
    providers,
)
from .test_vobiz import START

CALL_ID = START["start"]["callId"]


def form(**fields: str) -> dict[str, str]:
    return {"CallUUID": CALL_ID, "From": "+919876543210", "To": "+919100000001", **fields}


def stream_of(response_text: str) -> tuple[str, dict[str, list[str]]]:
    url = ET.fromstring(response_text.split("?>", 1)[1]).find("Stream").text  # type: ignore[union-attr]
    parsed = urlparse(url or "")
    return parsed.path, parse_qs(parsed.query)


def test_a_call_that_can_be_taken_gets_the_stream_for_the_right_employee(
    api: TestClient,
    migrated_url: str,
    providers: None,  # noqa: F811
) -> None:
    employee, _owner = inbound_employee(api, migrated_url)
    with TestClient(app) as client:
        response = client.post("/vobiz/inbound", data=form())
    assert response.status_code == 200 and response.headers["content-type"].startswith(
        "application/xml"
    )
    path, query = stream_of(response.text)
    (call,) = calls(migrated_url)
    assert path == "/vobiz/stream"
    assert query == {"lang": ["en"], "call": [str(call["id"])], "employee": [employee]}
    assert call["status"] == "ringing" and call["carrier_call_id"] == CALL_ID


def test_a_call_that_cannot_be_taken_is_rejected_and_recorded(
    api: TestClient,
    migrated_url: str,
    providers: None,  # noqa: F811
) -> None:
    inbound_employee(api, migrated_url, live=False)
    with TestClient(app) as client:
        response = client.post("/vobiz/inbound", data=form())
    assert response.status_code == 200 and '<Hangup reason="rejected"/>' in response.text
    (call,) = calls(migrated_url)
    assert call["status"] == "no_answer" and "paused" in call["miss_reason"]


def test_a_call_the_carrier_does_not_have_is_rejected_and_leaves_nothing(
    api: TestClient,
    migrated_url: str,
    providers: None,  # noqa: F811
) -> None:
    inbound_employee(api, migrated_url)
    _Carrier.live = False
    with TestClient(app) as client:
        response = client.post("/vobiz/inbound", data=form())
    assert '<Hangup reason="rejected"/>' in response.text
    assert calls(migrated_url) == []


def test_who_called_and_which_number_come_from_the_carrier_not_the_request(
    api: TestClient,
    migrated_url: str,
    providers: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Found by the SEC test: the answer URL is unsigned, so a request naming a live call id must
    not choose the caller or the number dialled."""
    employee, _owner = inbound_employee(api, migrated_url)
    monkeypatch.setattr(_Carrier, "parties", ("+919811112222", "+919100000001"))
    forged = form(From="+910000000000", To="+919100000099")
    with TestClient(app) as client:
        response = client.post("/vobiz/inbound", data=forged)
    _path, query = stream_of(response.text)
    (call,) = calls(migrated_url)
    assert query["employee"] == [employee] and call["caller_phone"] == "+919811112222"

    monkeypatch.setattr(_Carrier, "parties", ("+919811112222", "+919100000099"))  # not ours
    with TestClient(app) as client:
        response = client.post("/vobiz/inbound", data=form(CallUUID="other-live-call"))
    assert '<Hangup reason="rejected"/>' in response.text and len(calls(migrated_url)) == 1


def test_the_answer_needs_the_carrier_and_the_public_address(
    api: TestClient,
    migrated_url: str,
    providers: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inbound_employee(api, migrated_url)
    monkeypatch.delenv("AXON_ENGINE_PUBLIC_URL")
    with TestClient(app) as client:
        response = client.post("/vobiz/inbound", data=form())
    assert response.status_code == 503 and response.json()["missing_keys"] == [
        "AXON_ENGINE_PUBLIC_URL"
    ]


class _SpeaksWhatItIsToldTo(_Passthrough):
    """Stands in for TTS: a line to speak becomes its words and 300 ms of tone."""

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        if isinstance(frame, TTSSpeakFrame):
            await super().process_frame(frame, direction)
            await self.push_frame(TTSStartedFrame())
            await self.push_frame(TTSTextFrame(frame.text, text_type="sentence"))
            tone = bytes([0, 40]) * (16000 * 3 // 10)
            await self.push_frame(TTSAudioRawFrame(audio=tone, sample_rate=16000, num_channels=1))
            await self.push_frame(TTSStoppedFrame())
            return
        await super().process_frame(frame, direction)


def _voices_on_the_test_leg(url: str) -> None:
    """The seeded catalog names real vendors; the streams here run on the test-only leg."""
    sql(url, "UPDATE voices SET provider = 'testleg'")


def test_the_opening_is_spoken_before_the_caller_says_a_word(
    api: TestClient,
    migrated_url: str,
    providers: None,  # noqa: F811
    events: list[dict[str, Any]],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(SERVICES, (ProviderKind.TTS, "testleg"), lambda *_: _SpeaksWhatItIsToldTo())
    monkeypatch.setattr(engine.call, "MIN_CALL_S", 0)
    inbound_employee(api, migrated_url, settings={"greeting_new": "Welcome to {{business_name}}."})
    _voices_on_the_test_leg(migrated_url)
    with TestClient(app) as client:
        answered = client.post("/vobiz/inbound", data=form())
        _, query = stream_of(answered.text)
        link = f"/vobiz/stream?lang=en&call={query['call'][0]}&employee={query['employee'][0]}"
        with client.websocket_connect(link) as ws:
            ws.send_text(json.dumps(START))
            # The caller has sent no audio: whatever arrives first is the employee speaking.
            first = json.loads(ws.receive_text())
            assert first["event"] == "playAudio"
            for _ in range(10):
                ws.send_text(json.dumps({"event": "media", "media": {"payload": SILENCE_ULAW}}))
        deadline = time.monotonic() + 10
        while not (events and events[-1]["type"] == "ended") and time.monotonic() < deadline:
            time.sleep(0.05)
        # The row is written just after the last event goes out; leaving the client would cut it.
        while (
            sql(migrated_url, "SELECT status FROM calls") == "in_progress"
            and time.monotonic() < deadline
        ):
            time.sleep(0.05)
    said = " ".join(e["text"] for e in events if e["type"] == "bot_text")
    assert said.startswith("This call may be recorded for quality purposes. Welcome to Acme.")
    first_turn = next(e for e in events if e["type"] in ("bot_text", "user_transcript"))
    assert first_turn["type"] == "bot_text"
    (call,) = calls(migrated_url)
    assert call["status"] == "completed" and call["answered_at"] is not None
    assert call["transcript"][0]["role"] == "assistant"
    assert "recorded" in call["transcript"][0]["text"]


def test_an_outbound_call_has_no_opening_and_waits_to_be_spoken_to(
    api: TestClient,
    migrated_url: str,
    providers: None,  # noqa: F811
) -> None:
    from engine.plan import load_plan

    employee, _owner = inbound_employee(api, migrated_url, channel="instant")
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine

    async def plan() -> Any:
        db = create_async_engine(migrated_url)
        try:
            return await load_plan(db, employee)
        finally:
            await db.dispose()

    loaded = asyncio.run(plan())
    assert loaded.opening == "" and loaded.transfer_to is None
    assert sql(migrated_url, "SELECT count(*) FROM calls") == 0


def test_a_stream_for_a_call_the_carrier_does_not_have_is_refused_for_inbound_too(
    api: TestClient,
    migrated_url: str,
    providers: None,  # noqa: F811
) -> None:
    inbound_employee(api, migrated_url)
    _voices_on_the_test_leg(migrated_url)
    with TestClient(app) as client:
        answered = client.post("/vobiz/inbound", data=form())
        _, query = stream_of(answered.text)
        _Carrier.live = False
        link = f"/vobiz/stream?lang=en&call={query['call'][0]}&employee={query['employee'][0]}"
        with client.websocket_connect(link) as ws:
            ws.send_text(json.dumps(START))
            with pytest.raises(WebSocketDisconnect) as closed:
                ws.receive_text()
    assert closed.value.code == 1008
