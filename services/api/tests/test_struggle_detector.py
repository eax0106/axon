"""The struggle detector: moments on real calls where the employee fell short, in the words of
the call, as suggestions the owner can teach with one tap."""

import json
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.employees import runtime
from app.models import Employee
from app.providers.speech import common

from .conftest import sql
from .helpers import run_db, seed, signup
from .test_post_call_job import Gemini, make_call, model_reply, process, setup

TURNS = [
    {"role": "assistant", "text": "Hello, this is Asha from SunBright Solar. Is this a good time?"},
    {"role": "user", "text": "Yes. Do you give a subsidy for rooftop panels?"},
    {"role": "assistant", "text": "I am not sure about that, let me note it down."},
    {"role": "user", "text": "Okay. Stop pushing me, I said I will think about it."},
    {"role": "assistant", "text": "But this offer ends today, you must decide now!"},
    {"role": "user", "text": "Please call me tomorrow at 6 in the evening."},
]
GAP = {
    "reason": "unanswered",
    "caller_quote": "Do you give a subsidy for rooftop panels?",
    "agent_quote": "I am not sure about that",
}
PUSHY = {
    "reason": "conduct",
    "caller_quote": "Stop pushing me, I said I will think about it",
    "agent_quote": "this offer ends today, you must decide now",
    "rule": "Never pressure a caller who says they will think about it.",
}


@pytest.fixture
def api(
    db_client: TestClient, migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, Gemini]]:
    seed(migrated_url)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    fake = Gemini()
    transport = httpx.MockTransport(fake.handler)
    monkeypatch.setattr(
        common.VendorHealth,
        "client",
        lambda self, timeout=60.0: httpx.AsyncClient(transport=transport),
    )
    yield db_client, fake


def analyse(
    url: str, fake: Gemini, employee: str, struggles: list[Any], *, test_call: bool = False
) -> str:
    fake.text = model_reply(struggles=struggles)
    call = make_call(url, employee, TURNS, phone=f"+9198{uuid.uuid4().int % 10**8:08d}")
    if test_call:
        sql(url, "UPDATE calls SET is_test = true WHERE id = :c", {"c": call})
    assert process(url) == 1
    return call


def open_suggestions(client: TestClient, owner: dict[str, str], employee: str) -> list[Any]:
    response = client.get(f"/employees/{employee}/training/suggestions", headers=owner)
    return response.json()  # type: ignore[no-any-return]


def test_a_real_call_leaves_suggestions_that_quote_the_call(
    api: tuple[TestClient, Gemini], migrated_url: str
) -> None:
    client, fake = api
    employee, owner = setup(client, migrated_url)
    call = analyse(migrated_url, fake, employee, [GAP, PUSHY])
    found = {s["reason"]: s for s in open_suggestions(client, owner, employee)}
    gap, rule = found["unanswered"], found["conduct"]
    assert gap["kind"] == "fact" and gap["text"] == ""  # only the owner knows the answer
    assert gap["caller_quote"] == GAP["caller_quote"] and gap["call_id"] == call
    assert gap["agent_quote"] == "I am not sure about that"
    assert rule["kind"] == "rule" and rule["text"] == PUSHY["rule"]
    assert rule["agent_quote"] == PUSHY["agent_quote"]
    assert (
        client.get(f"/employees/{employee}/training", headers=owner).json()["open_suggestions"] == 2
    )
    assert (
        "struggles"
        in json.loads(fake.requests[-1].content)["systemInstruction"]["parts"][0]["text"]
    )


def test_nothing_the_transcript_does_not_show_becomes_a_suggestion(
    api: tuple[TestClient, Gemini], migrated_url: str
) -> None:
    client, fake = api
    employee, owner = setup(client, migrated_url)
    invented = [
        {**GAP, "caller_quote": "Do you give a loan for the panels?"},  # the caller never said it
        {**GAP, "caller_quote": "I am not sure about that"},  # the Agent said it, not the caller
        {**PUSHY, "agent_quote": "you will regret this"},  # the Agent never said it
        {**PUSHY, "agent_quote": None},  # a conduct fault must quote the Agent
        {**PUSHY, "rule": None},  # and carry a rule to teach
        {**GAP, "reason": "rude"},
        {**GAP, "caller_quote": "Yes."},  # too short to prove anything
        "nonsense",
    ]
    analyse(migrated_url, fake, employee, invented)
    assert open_suggestions(client, owner, employee) == []
    # A gap whose agent quote is made up still stands on the caller's real words, without it.
    analyse(migrated_url, fake, employee, [{**GAP, "agent_quote": "I have no idea at all"}])
    [kept] = open_suggestions(client, owner, employee)
    assert kept["caller_quote"] == GAP["caller_quote"] and kept["agent_quote"] is None


def test_at_most_three_a_call_and_none_from_a_test_call(
    api: tuple[TestClient, Gemini], migrated_url: str
) -> None:
    client, fake = api
    employee, owner = setup(client, migrated_url)
    analyse(migrated_url, fake, employee, [GAP, PUSHY], test_call=True)
    assert open_suggestions(client, owner, employee) == []
    second = {**GAP, "caller_quote": "Okay. Stop pushing me, I said I will think about it."}
    third = {**GAP, "caller_quote": "Please call me tomorrow at 6 in the evening."}
    fourth = {**GAP, "caller_quote": "Yes. Do you give a subsidy for rooftop panels?"}
    analyse(migrated_url, fake, employee, [GAP, PUSHY, second, third, fourth])
    assert len(open_suggestions(client, owner, employee)) == 3


def test_a_moment_the_owner_already_saw_does_not_come_back(
    api: tuple[TestClient, Gemini], migrated_url: str
) -> None:
    client, fake = api
    employee, owner = setup(client, migrated_url)
    analyse(migrated_url, fake, employee, [GAP])
    analyse(
        migrated_url,
        fake,
        employee,
        [{**GAP, "caller_quote": "do you GIVE a subsidy for rooftop panels"}],
    )
    [only] = open_suggestions(client, owner, employee)
    base = f"/employees/{employee}/training/suggestions/{only['id']}"
    assert client.post(f"{base}/dismiss", headers=owner).status_code == 204
    analyse(migrated_url, fake, employee, [GAP])
    assert open_suggestions(client, owner, employee) == []


def test_accepting_a_gap_needs_the_owners_answer_and_the_next_call_uses_it(
    api: tuple[TestClient, Gemini], migrated_url: str
) -> None:
    client, fake = api
    employee, owner = setup(client, migrated_url)
    analyse(migrated_url, fake, employee, [GAP])
    [gap] = open_suggestions(client, owner, employee)
    path = f"/employees/{employee}/training/suggestions/{gap['id']}/accept"
    assert client.post(path, json={}, headers=owner).status_code == 422  # nothing to teach yet
    assert open_suggestions(client, owner, employee) != []
    answer = "Yes, we help with the government subsidy paperwork."
    taught = client.post(path, json={"text": answer}, headers=owner)
    assert taught.status_code == 200 and taught.json()["taught"][0]["source"] == "suggestion"
    assert open_suggestions(client, owner, employee) == []
    assert client.post(path, json={"text": answer}, headers=owner).status_code == 409

    async def work(factory: Any) -> str:
        async with factory() as session:
            plan = await runtime.plan_for(
                session, await session.get(Employee, uuid.UUID(employee)), use_draft=True
            )
            assert plan is not None
            return plan.system_prompt

    assert f"- {answer}" in run_db(migrated_url, work)


def test_accepting_a_rule_takes_its_own_words_or_the_owners(
    api: tuple[TestClient, Gemini], migrated_url: str
) -> None:
    client, fake = api
    employee, owner = setup(client, migrated_url)
    analyse(migrated_url, fake, employee, [PUSHY])
    [rule] = open_suggestions(client, owner, employee)
    path = f"/employees/{employee}/training/suggestions/{rule['id']}/accept"
    taught = client.post(path, json={}, headers=owner).json()["taught"]
    assert [(t["kind"], t["text"]) for t in taught] == [("rule", PUSHY["rule"])]
    analyse(
        migrated_url, fake, employee, [{**PUSHY, "caller_quote": "Please call me tomorrow at 6"}]
    )
    [another] = open_suggestions(client, owner, employee)
    reworded = client.post(
        f"/employees/{employee}/training/suggestions/{another['id']}/accept",
        json={"text": "  Back off once they say no.  "},
        headers=owner,
    )
    assert reworded.json()["taught"][0]["text"] == "Back off once they say no."


def test_a_full_list_keeps_the_suggestion_open(
    api: tuple[TestClient, Gemini], migrated_url: str
) -> None:
    client, fake = api
    employee, owner = setup(client, migrated_url)
    client.post(
        f"/employees/{employee}/training/items",
        json={"items": [{"kind": "rule", "text": f"rule {n}"} for n in range(20)]},
        headers=owner,
    )
    analyse(migrated_url, fake, employee, [PUSHY])
    [rule] = open_suggestions(client, owner, employee)
    path = f"/employees/{employee}/training/suggestions/{rule['id']}"
    assert client.post(f"{path}/accept", json={}, headers=owner).status_code == 409
    assert len(open_suggestions(client, owner, employee)) == 1  # still there to be dealt with


def test_suggestions_are_the_accounts_own(
    api: tuple[TestClient, Gemini], migrated_url: str
) -> None:
    client, fake = api
    employee, owner = setup(client, migrated_url)
    other = signup(client, "b@example.com", "B")
    analyse(migrated_url, fake, employee, [GAP])
    [gap] = open_suggestions(client, owner, employee)
    path = f"/employees/{employee}/training/suggestions"
    assert client.get(path, headers=other).status_code == 404
    assert client.post(f"{path}/{gap['id']}/dismiss", headers=other).status_code == 404
    assert client.post(f"{path}/{uuid.uuid4()}/dismiss", headers=owner).status_code == 404
    assert client.post(f"{path}/{gap['id']}/dismiss", headers=owner).status_code == 204
    assert client.post(f"{path}/{gap['id']}/dismiss", headers=owner).status_code == 409
