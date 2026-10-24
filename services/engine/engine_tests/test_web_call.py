import asyncio
import base64
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pipecat.frames.frames import (
    InputAudioRawFrame,
    InputTransportMessageFrame,
    InterruptionFrame,
    OutputTransportMessageFrame,
    TTSAudioRawFrame,
)
from starlette.websockets import WebSocketDisconnect
from tests.helpers import seed, signup

from app.employees import tickets
from engine.main import app as engine_app
from engine.vobiz import checkpoint
from engine.web import WebFrameSerializer

PCM = b"\x01\x00" * 320


def test_audio_out_is_a_playaudio_message_and_other_rates_are_not_sent() -> None:
    serializer = WebFrameSerializer()
    sent = asyncio.run(
        serializer.serialize(TTSAudioRawFrame(audio=PCM, sample_rate=16000, num_channels=1))
    )
    assert json.loads(str(sent)) == {
        "event": "playAudio",
        "sampleRate": 16000,
        "payload": base64.b64encode(PCM).decode(),
    }
    wrong_rate = TTSAudioRawFrame(audio=PCM, sample_rate=8000, num_channels=1)
    assert asyncio.run(serializer.serialize(wrong_rate)) is None


def test_barge_in_and_checkpoints_reach_the_browser() -> None:
    serializer = WebFrameSerializer()
    assert json.loads(str(asyncio.run(serializer.serialize(InterruptionFrame())))) == {
        "event": "clearAudio"
    }
    sent = asyncio.run(serializer.serialize(checkpoint("utt-1")))
    assert json.loads(str(sent)) == {"event": "checkpoint", "name": "utt-1"}
    assert isinstance(checkpoint("x"), OutputTransportMessageFrame)


def test_media_in_becomes_caller_audio_and_playedstream_is_passed_on() -> None:
    serializer = WebFrameSerializer()
    media = json.dumps({"event": "media", "payload": base64.b64encode(PCM).decode()})
    frame = asyncio.run(serializer.deserialize(media))
    assert (
        isinstance(frame, InputAudioRawFrame) and frame.audio == PCM and frame.sample_rate == 16000
    )
    played = asyncio.run(
        serializer.deserialize(json.dumps({"event": "playedStream", "name": "utt-1"}))
    )
    assert isinstance(played, InputTransportMessageFrame) and played.message["name"] == "utt-1"


@pytest.mark.parametrize(
    "data", ["not json", "{}", '{"event": "media", "payload": ""}', '{"event": "x"}']
)
def test_junk_from_the_browser_is_dropped(data: str) -> None:
    assert asyncio.run(WebFrameSerializer().deserialize(data)) is None


@pytest.fixture
def api(db_client: TestClient, migrated_url: str, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    seed(migrated_url)
    monkeypatch.setenv("AXON_ENGINE_PUBLIC_URL", "https://engine.example.in")
    return db_client


def closed_with(ticket: str) -> WebSocketDisconnect:
    with (
        TestClient(engine_app) as engine,
        engine.websocket_connect(f"/web/stream?ticket={ticket}") as ws,
    ):
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    return closed.value


def test_the_stream_refuses_a_missing_forged_or_expired_ticket(api: TestClient) -> None:
    grant = tickets.WebTicket(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    late = tickets.issue(grant, now=datetime.now(UTC) - timedelta(minutes=5))
    login = signup(api)["Authorization"].removeprefix("Bearer ")
    for bad in ("", "forged", late, login):
        assert closed_with(bad).code == 1008, bad


def test_a_valid_ticket_for_an_unknown_employee_is_refused(api: TestClient) -> None:
    ticket = tickets.issue(tickets.WebTicket(uuid.uuid4(), uuid.uuid4(), uuid.uuid4()))
    assert closed_with(ticket).code == 1008


def test_a_valid_ticket_without_speech_keys_closes_with_provider_not_configured(
    api: TestClient,
) -> None:
    owner = signup(api)
    employee = api.post("/employees", json={"channel": "instant"}, headers=owner).json()
    web = api.post(f"/employees/{employee['id']}/web-test-call", headers=owner).json()
    closed = closed_with(web["ticket"])
    assert closed.code == 1011 and "provider_not_configured" in closed.reason
