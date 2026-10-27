"""In-call actions inside a real call: the AI gets the employee's tools, uses one while the
caller is on the line, and the call keeps going whatever the tool does."""

import asyncio
import json
import time
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pipecat.frames.frames import Frame, StartFrame
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection
from tests.actions_support import http_action
from tests.conftest import sql
from tests.inbound_support import calls, inbound_employee
from tests.inbound_support import events as stored_events

import engine.call
from app.actions.tools import Tool
from app.providers.base import ProviderKind
from engine.call import register_tools
from engine.main import app
from engine.services import SERVICES

from .test_call import SILENCE_ULAW, _Passthrough, events, providers  # noqa: F401
from .test_inbound_engine import form, stream_of
from .test_vobiz import START


class _FakeLLM:
    def __init__(self) -> None:
        self.registered: dict[str, tuple[Any, dict[str, Any]]] = {}

    def register_function(self, name: str, handler: Any, **options: Any) -> None:
        self.registered[name] = (handler, options)


class _Params:
    def __init__(self, arguments: dict[str, Any]) -> None:
        self.arguments = arguments
        self.results: list[Any] = []

    async def result_callback(self, result: Any, **_: Any) -> None:
        self.results.append(result)


def a_tool(name: str = "lookup", ok: bool = True) -> Tool:
    async def run(args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": ok, "answer": "private details", "echo": args}

    return Tool(name, "Looks something up.", {}, [], run, timeout_s=4.0)


def test_each_tool_is_registered_and_an_interruption_does_not_cancel_it() -> None:
    llm = _FakeLLM()
    register_tools(llm, (a_tool("one"), a_tool("two")), lambda _event: asyncio.sleep(0))  # type: ignore[arg-type]
    assert set(llm.registered) == {"one", "two"}
    _, options = llm.registered["one"]
    assert options["cancel_on_interruption"] is False and options["timeout_secs"] > 4.0


def test_the_result_goes_back_to_the_ai_and_only_the_fact_of_use_is_recorded() -> None:
    llm, seen = _FakeLLM(), []

    async def emit(event: dict[str, Any]) -> None:
        seen.append(event)

    register_tools(llm, (a_tool(),), emit)  # type: ignore[arg-type]
    params = _Params({"order_id": "9"})
    asyncio.run(llm.registered["lookup"][0](params))
    assert params.results[0]["answer"] == "private details" and params.results[0]["echo"] == {
        "order_id": "9"
    }
    [event] = seen
    assert set(event) == {"type", "name", "ok", "ms"}
    assert event["type"] == "action" and event["name"] == "lookup" and event["ok"] is True
    assert "private details" not in str(event) and "9" not in str(event["name"])


class _UsesATool(_Passthrough):
    """Stands in for the LLM: soon after the call starts it uses the employee's tool."""

    def __init__(self, tool: str, arguments: dict[str, Any]) -> None:
        super().__init__()
        self.tool, self.arguments = tool, arguments
        self.handlers: dict[str, Any] = {}
        self.params = _Params(arguments)
        self.used: asyncio.Task[None] | None = None

    def register_function(self, name: str, handler: Any, **_: Any) -> None:
        self.handlers[name] = handler

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, StartFrame) and self.tool in self.handlers:
            self.used = asyncio.create_task(self._use())

    async def _use(self) -> None:
        await asyncio.sleep(0.3)
        await self.handlers[self.tool](self.params)


def _call_with_action(
    api: TestClient,
    url: str,
    llm: _UsesATool,
    monkeypatch: pytest.MonkeyPatch,
    action: dict[str, Any] | None = None,
    prepare: Callable[[str, dict[str, str]], None] | None = None,
) -> None:
    """Take a call as a new inbound employee; `prepare(employee, owner)` may teach it first."""
    monkeypatch.setitem(SERVICES, (ProviderKind.LLM, "testleg"), lambda *_: llm)
    employee, owner = inbound_employee(api, url, settings={})
    if action is not None:
        assert api.put(f"/employees/{employee}/actions", json={"actions": [action]}, headers=owner)
    if prepare is not None:
        prepare(employee, owner)
    assert api.post(f"/employees/{employee}/publish", headers=owner).status_code == 200
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
            while time.monotonic() < deadline and not llm.params.results:
                time.sleep(0.05)
            time.sleep(0.3)
        # The call is written up after the stream closes.
        ended = "SELECT count(*) FROM call_events WHERE type = 'ended'"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and sql(url, ended) == 0:
            time.sleep(0.05)


def test_the_ai_is_offered_the_employees_action_and_gets_the_services_answer(
    api: TestClient,
    migrated_url: str,
    providers: None,  # noqa: F811
    events: list[dict[str, Any]],  # noqa: F811
    shop: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.actions_support import Shop

    monkeypatch.setattr(engine.call, "MIN_CALL_S", 0)
    offered: list[list[str]] = []
    real_context = LLMContext

    def spy(*args: Any, **kwargs: Any) -> Any:
        offered.append([t.name for t in kwargs["tools"].standard_tools])
        return real_context(*args, **kwargs)

    monkeypatch.setattr(engine.call, "LLMContext", spy)
    llm = _UsesATool("order_status", {"order_id": "9"})
    _call_with_action(
        api, migrated_url, llm, monkeypatch, http_action(url=shop + "/orders/{order_id}")
    )

    assert offered == [["end_call", "order_status"]]
    assert Shop.seen[-1]["path"] == "/orders/9"
    [result] = llm.params.results
    assert result["ok"] is True and json.loads(result["result"])["path"] == "/orders/9"
    [action] = [e for e in events if e["type"] == "action"]
    assert action["name"] == "order_status" and action["ok"] is True
    assert "/orders/9" not in json.dumps(action)  # not the question and not the answer
    (call,) = calls(migrated_url)
    recorded = [d for t, d in stored_events(migrated_url, call["id"]) if t == "action"]
    assert [d["name"] for d in recorded] == ["order_status"]  # kept on the call's timeline


def test_a_failing_service_gives_the_ai_a_plain_failure_and_the_call_goes_on(
    api: TestClient,
    migrated_url: str,
    providers: None,  # noqa: F811
    events: list[dict[str, Any]],  # noqa: F811
    shop: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine.call, "MIN_CALL_S", 0)
    llm = _UsesATool("order_status", {"order_id": "9"})
    down = http_action(url=shop + "/boom/{order_id}")
    _call_with_action(api, migrated_url, llm, monkeypatch, down)
    [result] = llm.params.results
    assert result["ok"] is False and "refused or failed" in result["error"]
    [action] = [e for e in events if e["type"] == "action"]
    assert action["ok"] is False
    assert "ended" not in [e["type"] for e in events[: events.index(action)]]
