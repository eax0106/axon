"""Handing a live call to a person: the tool, the carrier request, the XML, and what is recorded."""

import asyncio
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from pipecat.frames.frames import Frame, LLMContextFrame, StartFrame
from pipecat.processors.frame_processor import FrameDirection
from tests.conftest import sql
from tests.inbound_support import NUMBER, calls, inbound_employee
from tests.inbound_support import events as stored_events

import engine.call
from app.employees.tickets import issue_call_ticket
from app.providers.base import ProviderKind
from engine.call import TRANSFER_FAILED, TRANSFER_TO_HUMAN
from engine.goodbye import GoodbyeGate
from engine.main import RESULT_TICKET_TTL, TRANSFER_TICKET_TTL, app
from engine.services import SERVICES

from .test_call import SILENCE_ULAW, _Carrier, _Passthrough, events, providers  # noqa: F401
from .test_inbound_engine import form, stream_of
from .test_vobiz import START

PERSON = "+919811112222"
STATUS = {"DialStatus": "completed"}
SETTINGS = {"transfer_number": PERSON, "transfer_when": "The caller asks for the owner."}


class _AsksForAPerson(_Passthrough):
    """Stands in for the LLM: soon after the call starts it calls `transfer_to_human`."""

    def __init__(self) -> None:
        super().__init__()
        self.handlers: dict[str, Any] = {}
        self.context: list[Any] = []
        self._ask: asyncio.Task[None] | None = None

    def register_function(self, name: str, handler: Any) -> None:
        self.handlers[name] = handler

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame):
            self.context = list(frame.context.get_messages())
        if isinstance(frame, StartFrame) and "transfer_to_human" in self.handlers:
            self._ask = asyncio.create_task(self._ask_for_a_person())

    async def _ask_for_a_person(self) -> None:
        await asyncio.sleep(0.3)

        class Params:
            async def result_callback(self, *_: Any, **__: Any) -> None:
                return None

        await self.handlers["transfer_to_human"](Params())


def settle_gate_for(end: Callable[[str], Awaitable[None]]) -> GoodbyeGate:
    return GoodbyeGate(end, settle_s=0.02, timeout_s=0.5)


def settle_gate(ended: list[str]) -> GoodbyeGate:
    async def end(reason: str) -> None:
        ended.append(reason)

    return settle_gate_for(end)


def test_the_gate_runs_what_it_is_given_once_the_speech_is_heard_and_not_before() -> None:
    async def run() -> tuple[list[str], list[str]]:
        ended: list[str] = []
        done: list[str] = []

        async def then() -> None:
            done.append("then")

        gate = settle_gate(ended)
        gate.tts_started()
        gate.checkpoint_issued("utt-1")
        gate.tts_stopped()
        await gate.request_end(then)
        await asyncio.sleep(0.1)
        early = list(done)
        gate.played_stream("utt-1")
        await asyncio.sleep(0.1)
        return early, done

    early, done = asyncio.run(run())
    assert early == [] and done == ["then"]


def test_a_reopened_gate_can_be_asked_again() -> None:
    async def run() -> list[str]:
        ended: list[str] = []
        done: list[str] = []

        async def then() -> None:
            done.append("then")

        gate = settle_gate(ended)
        await gate.request_end(then)
        await asyncio.sleep(0.1)
        await gate.request_end(then)  # still the same request: nothing more happens
        await asyncio.sleep(0.1)
        gate.reopen()
        await gate.request_end(then)
        await asyncio.sleep(0.1)
        return done

    assert asyncio.run(run()) == ["then", "then"]


def test_the_tool_is_named_and_takes_nothing() -> None:
    assert TRANSFER_TO_HUMAN.name == "transfer_to_human" and TRANSFER_TO_HUMAN.required == []


def _stream(
    api: TestClient,
    url: str,
    llm: _AsksForAPerson,
    monkeypatch: pytest.MonkeyPatch,
    until: Callable[[str], bool],
) -> None:
    """Answer an incoming call, stream audio and let the AI ask for a person, until `until`.
    No carrier confirms what was played, so the gate gives up waiting for it quickly."""
    monkeypatch.setattr(engine.call, "GoodbyeGate", lambda end: settle_gate_for(end))
    monkeypatch.setitem(SERVICES, (ProviderKind.LLM, "testleg"), lambda *_: llm)
    inbound_employee(api, url, settings=SETTINGS)
    sql(url, "UPDATE voices SET provider = 'testleg'")
    with TestClient(app) as client:
        answered = client.post("/vobiz/inbound", data=form())
        _, query = stream_of(answered.text)
        link = f"/vobiz/stream?lang=en&call={query['call'][0]}&employee={query['employee'][0]}"
        with client.websocket_connect(link) as ws:
            ws.send_text(json.dumps(START))
            for _ in range(20):
                ws.send_text(json.dumps({"event": "media", "media": {"payload": SILENCE_ULAW}}))
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and not until(url):
                time.sleep(0.05)


def test_the_call_stays_up_through_the_hand_over_and_the_carrier_then_rings_the_person(
    api: TestClient,
    migrated_url: str,
    providers: None,  # noqa: F811
    events: list[dict[str, Any]],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    moved: list[tuple[str, str]] = []

    async def transfer(_self: Any, call_uuid: str, instructions_url: str) -> None:
        moved.append((call_uuid, instructions_url))

    monkeypatch.setattr(_Carrier, "transfer", transfer)
    _stream(
        api,
        migrated_url,
        _AsksForAPerson(),
        monkeypatch,
        lambda url: sql(migrated_url, "SELECT count(*) FROM call_events WHERE type = 'ended'") == 1,
    )

    ((uuid, link),) = moved
    assert uuid == START["start"]["callId"]
    parsed = urlparse(link)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "https://engine.example.in/vobiz/transfer"
    )
    assert _Carrier.hangups == []  # the carrier now owns the call
    types = [e["type"] for e in events]
    assert "transferred" in types and events[-1] == {"type": "ended", "reason": "transferred"}
    (call,) = calls(migrated_url)
    # Our stream is over, but the caller is still on the line: the call is up and holds its channel.
    assert call["status"] == "in_progress" and call["ended_at"] is None
    assert call["transcript"] is not None and call["analysis_status"] == "pending"
    assert "transferred" in [t for t, _ in stored_events(migrated_url, call["id"])]
    with TestClient(app) as client:
        other = client.post("/vobiz/inbound", data=form(CallUUID="leg-other", From="+919000000009"))
        assert "<Hangup" in other.text  # a one-channel number: the second caller finds it busy
        # What the carrier fetches next, after the stream is gone, must still ring the person.
        instructions = client.get(f"{parsed.path}?{parsed.query}")
        dial = ET.fromstring(instructions.text.split("?>", 1)[1]).find("Dial")
        assert dial is not None and dial.findtext("Number") == PERSON
        report = urlparse(dial.get("action") or "")
        done = client.post(
            report.path, params={"ticket": parse_qs(report.query)["ticket"][0]}, data=STATUS
        )
        assert done.status_code == 200
    (call,) = calls(migrated_url, f"carrier_leg_id = '{START['start']['callId']}'")
    assert call["status"] == "completed" and call["ended_at"] is not None


def test_a_transfer_the_carrier_refuses_keeps_the_call_and_tells_the_ai(
    api: TestClient,
    migrated_url: str,
    providers: None,  # noqa: F811
    events: list[dict[str, Any]],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def transfer(*_: Any) -> None:
        raise RuntimeError("carrier said 500")

    monkeypatch.setattr(_Carrier, "transfer", transfer)
    llm = _AsksForAPerson()
    _stream(
        api,
        migrated_url,
        llm,
        monkeypatch,
        lambda _url: any(
            m.get("content") == TRANSFER_FAILED for m in llm.context if isinstance(m, dict)
        ),
    )

    assert any(m.get("content") == TRANSFER_FAILED for m in llm.context if isinstance(m, dict))
    assert "transferred" not in [e["type"] for e in events]


def test_without_a_transfer_number_the_ai_has_no_such_tool(
    api: TestClient,
    migrated_url: str,
    providers: None,  # noqa: F811
    events: list[dict[str, Any]],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = _AsksForAPerson()
    monkeypatch.setitem(SERVICES, (ProviderKind.LLM, "testleg"), lambda *_: llm)
    inbound_employee(api, migrated_url, settings={})
    sql(migrated_url, "UPDATE voices SET provider = 'testleg'")
    with TestClient(app) as client:
        answered = client.post("/vobiz/inbound", data=form())
        _, query = stream_of(answered.text)
        link = f"/vobiz/stream?lang=en&call={query['call'][0]}&employee={query['employee'][0]}"
        with client.websocket_connect(link) as ws:
            ws.send_text(json.dumps(START))
            time.sleep(0.5)
    assert "transfer_to_human" not in llm.handlers and "end_call" in llm.handlers


def _live_inbound_call(api: TestClient, url: str) -> str:
    inbound_employee(api, url, settings=SETTINGS)
    with TestClient(app) as client:
        client.post("/vobiz/inbound", data=form())
    sql(url, "UPDATE calls SET status = 'in_progress'")
    (call,) = calls(url)
    return str(call["id"])


def test_the_instructions_ring_the_owners_person_and_show_our_own_number(
    api: TestClient,
    migrated_url: str,
    providers: None,  # noqa: F811
) -> None:
    call_id = _live_inbound_call(api, migrated_url)
    ticket = issue_call_ticket("transfer", uuid.UUID(call_id), TRANSFER_TICKET_TTL)
    with TestClient(app) as client:
        response = client.get("/vobiz/transfer", params={"ticket": ticket})
        post = client.post("/vobiz/transfer", params={"ticket": ticket})
    assert response.status_code == 200 and post.status_code == 200
    dial = ET.fromstring(response.text.split("?>", 1)[1]).find("Dial")
    assert dial is not None
    assert dial.get("callerId") == NUMBER
    assert dial.findtext("Number") == PERSON
    assert dial.get("method") == "POST"
    result = urlparse(dial.get("action") or "")
    assert result.path == "/vobiz/transfer-result" and parse_qs(result.query)["ticket"]


@pytest.mark.parametrize("ticket", ["", "garbage"])
def test_the_transfer_urls_are_closed_without_a_ticket_made_for_them(
    api: TestClient,
    migrated_url: str,
    providers: None,  # noqa: F811
    ticket: str,
) -> None:
    call_id = _live_inbound_call(api, migrated_url)
    wrong_kind = issue_call_ticket("transfer_result", uuid.UUID(call_id), RESULT_TICKET_TTL)
    with TestClient(app) as client:
        assert client.get("/vobiz/transfer", params={"ticket": ticket}).status_code == 403
        assert client.get("/vobiz/transfer", params={"ticket": wrong_kind}).status_code == 403
        assert client.post("/vobiz/transfer-result", params={"ticket": ticket}).status_code == 403


def test_a_call_that_is_not_live_gets_a_hang_up_not_a_dial(
    api: TestClient,
    migrated_url: str,
    providers: None,  # noqa: F811
) -> None:
    call_id = _live_inbound_call(api, migrated_url)
    sql(migrated_url, "UPDATE calls SET status = 'completed'")
    ticket = issue_call_ticket("transfer", uuid.UUID(call_id), TRANSFER_TICKET_TTL)
    with TestClient(app) as client:
        response = client.get("/vobiz/transfer", params={"ticket": ticket})
    root = ET.fromstring(response.text.split("?>", 1)[1])
    assert root.find("Dial") is None and root.find("Hangup") is not None


@pytest.mark.parametrize(
    ("dial_status", "messages"), [("completed", 0), ("no-answer", 1), ("busy", 1)]
)
def test_the_result_is_recorded_and_an_unconnected_transfer_leaves_a_message(
    api: TestClient,
    migrated_url: str,
    providers: None,  # noqa: F811
    dial_status: str,
    messages: int,
) -> None:
    call_id = _live_inbound_call(api, migrated_url)
    ticket = issue_call_ticket("transfer_result", uuid.UUID(call_id), RESULT_TICKET_TTL)
    with TestClient(app) as client:
        response = client.post(
            "/vobiz/transfer-result",
            params={"ticket": ticket},
            data={"DialStatus": dial_status},
        )
    assert response.status_code == 200 and "<Hangup" in response.text
    found = [(t, d) for t, d in stored_events(migrated_url, call_id) if t == "transfer_result"]
    assert found == [("transfer_result", {"status": dial_status})]
    (call,) = calls(migrated_url)  # the result is also the end of the call, and frees its channel
    assert call["status"] == "completed" and call["ended_at"] is not None
    assert sql(migrated_url, "SELECT count(*) FROM inbound_messages") == messages
