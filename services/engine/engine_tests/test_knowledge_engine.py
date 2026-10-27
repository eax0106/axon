"""Documents inside a real call: the AI is offered the look-up only when the employee has
documents, gets the passages back, and the call goes on whatever the look-up does."""

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pipecat.processors.aggregators.llm_context import LLMContext
from tests.knowledge_vendor import Vendor

import engine.call
from app.providers.speech import common

from .test_actions_engine import _call_with_action, _UsesATool
from .test_call import events, providers  # noqa: F401

PREMIUM = "Premium plan costs 4999 rupees a month."


@pytest.fixture
def gemini(monkeypatch: pytest.MonkeyPatch) -> Vendor:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    fake = Vendor()
    transport = httpx.MockTransport(fake.handler)
    monkeypatch.setattr(
        common.VendorHealth,
        "client",
        lambda self, timeout=60.0: httpx.AsyncClient(transport=transport),
    )
    return fake


def spy_on_the_call(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    seen: list[dict[str, Any]] = []
    real = LLMContext

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(
            {
                "tools": [t.name for t in kwargs["tools"].standard_tools],
                "prompt": kwargs["messages"][0]["content"],
            }
        )
        return real(*args, **kwargs)

    monkeypatch.setattr(engine.call, "LLMContext", spy)
    return seen


def teach_a_price_list(api: TestClient) -> Any:
    def prepare(employee: str, owner: dict[str, str]) -> None:
        response = api.post(
            f"/employees/{employee}/training/documents",
            params={"name": "prices"},
            content=PREMIUM.encode(),
            headers={**owner, "Content-Type": "text/plain"},
        )
        assert response.status_code == 201

    return prepare


def test_an_employee_without_documents_is_not_offered_the_look_up(
    api: TestClient,
    migrated_url: str,
    providers: None,  # noqa: F811
    events: list[dict[str, Any]],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = spy_on_the_call(monkeypatch)
    _call_with_action(api, migrated_url, _UsesATool("nothing", {}), monkeypatch)
    assert [s["tools"] for s in seen] == [["end_call"]]
    assert "look_up_knowledge" not in seen[0]["prompt"]


def test_the_ai_looks_in_the_documents_and_only_the_fact_of_use_is_recorded(
    api: TestClient,
    migrated_url: str,
    providers: None,  # noqa: F811
    events: list[dict[str, Any]],  # noqa: F811
    gemini: Vendor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = spy_on_the_call(monkeypatch)
    llm = _UsesATool("look_up_knowledge", {"question": "How much does the premium plan cost?"})
    _call_with_action(api, migrated_url, llm, monkeypatch, prepare=teach_a_price_list(api))
    assert [s["tools"] for s in seen] == [["end_call", "look_up_knowledge"]]
    assert "call the look_up_knowledge function" in seen[0]["prompt"]
    [result] = llm.params.results
    assert result == {"ok": True, "passages": [{"from": "prices", "text": PREMIUM}]}
    [used] = [e for e in events if e["type"] == "action"]
    assert used["name"] == "look_up_knowledge" and used["ok"] is True
    assert "premium" not in json.dumps(used).lower() and "4999" not in json.dumps(used)


def test_a_look_up_that_finds_nothing_or_fails_never_ends_the_call(
    api: TestClient,
    migrated_url: str,
    providers: None,  # noqa: F811
    events: list[dict[str, Any]],  # noqa: F811
    gemini: Vendor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepare = teach_a_price_list(api)

    def then_the_vendor_goes_down(employee: str, owner: dict[str, str]) -> None:
        prepare(employee, owner)
        gemini.embed_status = 500

    llm = _UsesATool("look_up_knowledge", {"question": "How much is the premium plan?"})
    _call_with_action(api, migrated_url, llm, monkeypatch, prepare=then_the_vendor_goes_down)
    [result] = llm.params.results
    assert result == {"ok": False, "error": "that is not available right now"}
    [used] = [e for e in events if e["type"] == "action"]
    assert used["ok"] is False
    assert "ended" not in [e["type"] for e in events[: events.index(used)]]
