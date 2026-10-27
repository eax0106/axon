"""The look-up function the AI gets during a call: it never raises and never ends the call."""

import asyncio
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.actions import tools as action_tools
from app.training import knowledge, tool
from app.training.tool import knowledge_tool

from .actions_support import http_action
from .helpers import run_db, seed, signup
from .knowledge_vendor import Vendor, hire


@pytest.fixture
def api(db_client: TestClient, migrated_url: str) -> TestClient:
    seed(migrated_url)
    return db_client


def employee_with(api: TestClient, text: str) -> tuple[str, dict[str, str]]:
    owner = signup(api)
    employee = hire(api, owner)
    response = api.post(
        f"/employees/{employee}/training/documents",
        params={"name": "prices"},
        content=text.encode(),
        headers={**owner, "Content-Type": "text/plain"},
    )
    assert response.status_code == 201
    return employee, owner


def look_up(url: str, employee: str, args: dict[str, Any]) -> dict[str, Any]:
    async def work(factory: Any) -> dict[str, Any]:
        return await knowledge_tool(factory, uuid.UUID(employee)).run(args)

    return run_db(url, work)  # type: ignore[no-any-return]


def test_it_returns_the_passages_or_says_there_are_none(
    api: TestClient, teaching: Vendor, migrated_url: str
) -> None:
    employee, _ = employee_with(api, "Premium plan costs 4999 rupees a month.")
    found = look_up(migrated_url, employee, {"question": "premium plan price"})
    assert found == {
        "ok": True,
        "passages": [{"from": "prices", "text": "Premium plan costs 4999 rupees a month."}],
    }
    nothing = look_up(migrated_url, employee, {"question": "do you repair bicycles"})
    assert nothing["ok"] is True and nothing["passages"] == []
    assert "nothing" in nothing["note"]


def test_a_blank_question_is_a_plain_failure_and_a_long_one_is_cut(
    api: TestClient, teaching: Vendor, migrated_url: str
) -> None:
    employee, _ = employee_with(api, "Premium plan costs 4999 rupees a month.")
    assert look_up(migrated_url, employee, {"question": "  "}) == {
        "ok": False,
        "error": "a question is needed",
    }
    assert look_up(migrated_url, employee, {})["ok"] is False
    look_up(migrated_url, employee, {"question": "premium " * 100})
    asked = teaching.sent(":batchEmbedContents")[-1]["requests"][0]["content"]["parts"][0]["text"]
    assert len(asked) <= 300


def test_it_never_raises_whatever_goes_wrong(
    api: TestClient,
    teaching: Vendor,
    migrated_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    employee, _ = employee_with(api, "Premium plan costs 4999 rupees a month.")
    plain = {"ok": False, "error": "that is not available right now"}
    teaching.embed_status = 500  # the vendor is down
    assert look_up(migrated_url, employee, {"question": "premium plan"}) == plain
    teaching.embed_status = 200
    monkeypatch.delenv("GEMINI_API_KEY")  # the key was removed
    assert look_up(migrated_url, employee, {"question": "premium plan"}) == plain

    async def slow(*_: Any) -> list[Any]:
        await asyncio.sleep(5)
        return []

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(tool, "look_up", slow)
    monkeypatch.setattr(tool, "TIMEOUT_S", 0.05)
    monkeypatch.setattr(action_tools, "GRACE_S", 0.05)
    assert look_up(migrated_url, employee, {"question": "premium plan"}) == plain  # cut short


def test_the_tool_describes_itself_and_the_name_is_reserved(
    api: TestClient, teaching: Vendor
) -> None:
    built = knowledge_tool(None, uuid.uuid4())  # type: ignore[arg-type]
    assert built.name == "look_up_knowledge" and built.required == ["question"]
    assert built.timeout_s == tool.TIMEOUT_S == 8.0
    owner = signup(api)
    employee = hire(api, owner)
    clash = http_action(name="look_up_knowledge")
    response = api.put(f"/employees/{employee}/actions", json={"actions": [clash]}, headers=owner)
    assert response.status_code == 422 and "look_up_knowledge" in response.text
    assert knowledge.TOP_K == 3
