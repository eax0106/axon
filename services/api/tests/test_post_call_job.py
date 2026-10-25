"""The post-call job against a real database and the real Gemini adapter (recorded replies)."""

import asyncio
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.calls import postcall
from app.models import Call
from app.providers.speech import common

from .conftest import sql
from .helpers import live_employee, run_db, seed, signup

NOW = datetime(2026, 11, 2, 8, 0, tzinfo=UTC)  # 13:30 IST on a Monday
TURNS = [
    {"role": "assistant", "text": "Hello, this is Asha from SunBright Solar. Is this a good time?"},
    {"role": "user", "text": "Yes. I am in Hyderabad and my budget is around five lakh rupees."},
    {"role": "user", "text": "Please call me tomorrow at 6 in the evening."},
]


class Gemini:
    def __init__(self) -> None:
        self.text = ""
        self.status = 200
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = {"candidates": [{"content": {"role": "model", "parts": [{"text": self.text}]}}]}
        return httpx.Response(self.status, json=body)

    def prompt(self, index: int = -1) -> str:
        sent = json.loads(self.requests[index].content)
        return str(sent["contents"][0]["parts"][0]["text"])


def model_reply(**changes: Any) -> str:
    base: dict[str, Any] = {
        "summary": "Asha called about solar panels.",
        "sentiment": "positive",
        "outcome": "callback_requested",
        "captured": {
            "budget": {"value": "five lakh", "quote": "my budget is around five lakh rupees"},
            "city": {"value": "Hyderabad", "quote": "I am in Hyderabad"},
        },
        "callback": {
            "at": "2026-11-03T18:00:00+05:30",
            "quote": "call me tomorrow at 6 in the evening",
        },
        "do_not_call": {"requested": False, "quote": None},
        "memory": "Lives in Hyderabad.",
    }
    base.update(changes)
    return json.dumps(base)


@pytest.fixture
def api(
    db_client: TestClient, migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, Gemini]]:
    seed(migrated_url)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    fake = Gemini()
    fake.text = model_reply()
    transport = httpx.MockTransport(fake.handler)
    monkeypatch.setattr(
        common.VendorHealth,
        "client",
        lambda self, timeout=60.0: httpx.AsyncClient(transport=transport),
    )
    yield db_client, fake


def make_call(
    url: str,
    employee: str,
    turns: list[dict[str, Any]] | None = TURNS,
    phone: str = "+919876543210",
    status: str = "pending",
    channel: str = "instant",
) -> str:
    account = sql(url, "SELECT account_id FROM employees WHERE id = :e", {"e": employee})
    lead = sql(url, "SELECT id FROM leads WHERE phone = :p", {"p": phone})
    if lead is None:
        lead = sql(
            url,
            "INSERT INTO leads (account_id, phone, name) VALUES (:a, :p, 'Ravi') RETURNING id",
            {"a": account, "p": phone},
        )
    call = sql(
        url,
        "INSERT INTO calls (account_id, employee_id, lead_id, direction, channel, status, ended_at,"
        " transcript, analysis_status) VALUES (:a, :e, :l, 'outbound', :c, 'completed', now(),"
        " CAST(:t AS jsonb), :s) RETURNING id",
        {"a": account, "e": employee, "l": lead, "c": channel, "t": json.dumps(turns), "s": status},
    )
    return str(call)


def setup(api: TestClient, url: str) -> tuple[str, dict[str, str]]:
    owner = signup(api)
    employee = live_employee(api, url, owner)
    api.put(
        f"/employees/{employee}/settings",
        json={
            "capture": [
                {"name": "budget", "description": "Monthly budget"},
                {"name": "city", "description": "City"},
            ]
        },
        headers=owner,
    )
    return employee, owner


def process(url: str, now: datetime = NOW) -> int:
    async def work(factory: Any) -> int:
        return await postcall.process_pending(factory, now)

    return run_db(url, work)  # type: ignore[no-any-return]


def row(url: str, call: str, column: str) -> Any:
    return sql(url, f"SELECT {column} FROM calls WHERE id = :c", {"c": call})  # noqa: S608


def test_a_pending_call_gets_its_summary_outcome_and_captured_fields(
    api: tuple[TestClient, Gemini], migrated_url: str
) -> None:
    client, _ = api
    employee, _ = setup(client, migrated_url)
    call = make_call(migrated_url, employee)
    assert process(migrated_url) == 1
    assert row(migrated_url, call, "summary") == "Asha called about solar panels."
    assert row(migrated_url, call, "sentiment") == "positive"
    assert row(migrated_url, call, "outcome") == "callback_requested"
    assert (
        row(migrated_url, call, "captured::text") == '{"city": "Hyderabad", "budget": "five lakh"}'
    )
    assert row(migrated_url, call, "analysis_status") == "done"
    assert process(migrated_url) == 0  # a done call is never analysed twice


def test_an_unsupported_value_never_reaches_the_database(
    api: tuple[TestClient, Gemini], migrated_url: str
) -> None:
    client, fake = api
    employee, _ = setup(client, migrated_url)
    fake.text = model_reply(
        captured={
            "budget": {"value": "ten crore", "quote": "my budget is ten crore"},
            "city": {"value": "Hyderabad", "quote": "I am in Hyderabad"},
        }
    )
    call = make_call(migrated_url, employee)
    process(migrated_url)
    assert row(migrated_url, call, "captured::text") == '{"city": "Hyderabad"}'


def test_a_callback_becomes_a_queued_call_inside_the_calling_window(
    api: tuple[TestClient, Gemini], migrated_url: str
) -> None:
    client, fake = api
    employee, owner = setup(client, migrated_url)
    call = make_call(migrated_url, employee)
    process(migrated_url)
    queued = sql(
        migrated_url,
        "SELECT status::text || is_callback::text || attempt::text FROM calls WHERE is_callback",
    )
    assert queued == "queuedtrue1"
    assert sql(migrated_url, "SELECT scheduled_for FROM calls WHERE is_callback") == datetime(
        2026, 11, 3, 12, 30, tzinfo=UTC
    )
    notes = client.get("/notifications", headers=owner).json()
    assert [n["kind"] for n in notes["items"]] == ["callback_scheduled"]
    assert "Ravi" in notes["items"][0]["body"] and "03 Nov, 18:00" in notes["items"][0]["body"]
    # A second call from the same person asking again does not stack callbacks.
    make_call(migrated_url, employee)
    process(migrated_url)
    assert sql(migrated_url, "SELECT count(*) FROM calls WHERE is_callback") == 1
    assert row(migrated_url, call, "analysis_status") == "done" and fake.requests


def test_a_callback_asked_for_at_night_waits_for_the_next_window(
    api: tuple[TestClient, Gemini], migrated_url: str
) -> None:
    client, fake = api
    employee, _ = setup(client, migrated_url)
    fake.text = model_reply(
        callback={
            "at": "2026-11-03T23:30:00+05:30",
            "quote": "call me tomorrow at 6 in the evening",
        }
    )
    make_call(migrated_url, employee)
    process(migrated_url)
    when = sql(migrated_url, "SELECT scheduled_for FROM calls WHERE is_callback")
    assert when == datetime(2026, 11, 4, 3, 30, tzinfo=UTC)  # 09:00 IST, the default window opening


def test_a_callback_works_on_any_channel(api: tuple[TestClient, Gemini], migrated_url: str) -> None:
    client, _ = api
    owner = signup(client)
    inbound = live_employee(client, migrated_url, owner, channel="inbound")
    make_call(migrated_url, inbound, channel="inbound")
    process(migrated_url)
    assert sql(migrated_url, "SELECT channel::text FROM calls WHERE is_callback") == "inbound"


def test_do_not_call_adds_the_number_cancels_waiting_calls_and_says_so(
    api: tuple[TestClient, Gemini], migrated_url: str
) -> None:
    client, fake = api
    employee, owner = setup(client, migrated_url)
    turns = [*TURNS, {"role": "user", "text": "Stop calling me. Do not call me again."}]
    fake.text = model_reply(do_not_call={"requested": True, "quote": "Do not call me again"})
    call = make_call(migrated_url, employee, turns)
    waiting = sql(
        migrated_url,
        "INSERT INTO calls (account_id, employee_id, lead_id, direction, channel, status,"
        " scheduled_for) SELECT account_id, employee_id, lead_id, 'outbound', 'instant', 'queued',"
        " now() FROM calls"
        " WHERE id = :c RETURNING id",
        {"c": call},
    )
    process(migrated_url)
    assert row(migrated_url, call, "outcome") == "do_not_call"
    assert (
        sql(migrated_url, "SELECT source::text FROM dnc_entries WHERE phone = '+919876543210'")
        == "caller_request"
    )
    assert row(migrated_url, str(waiting), "status::text") == "canceled"
    assert (
        sql(migrated_url, "SELECT count(*) FROM calls WHERE is_callback") == 0
    )  # asking not to be called wins
    kinds = [n["kind"] for n in client.get("/notifications", headers=owner).json()["items"]]
    assert kinds == ["do_not_call_added"]
    make_call(migrated_url, employee, turns)
    process(migrated_url)
    assert sql(migrated_url, "SELECT count(*) FROM dnc_entries") == 1
    assert len(client.get("/notifications", headers=owner).json()["items"]) == 1


def test_caller_memory_is_written_when_on_and_left_alone_when_off(
    api: tuple[TestClient, Gemini], migrated_url: str
) -> None:
    client, fake = api
    employee, owner = setup(client, migrated_url)
    make_call(migrated_url, employee)
    process(migrated_url)
    assert sql(migrated_url, "SELECT memory FROM leads") == "Lives in Hyderabad."
    assert "Lives in Hyderabad." not in fake.prompt(
        0
    )  # nothing was remembered before the first call
    assert (
        client.put("/account/caller-memory", json={"enabled": False}, headers=owner).status_code
        == 200
    )
    fake.text = model_reply(memory="Hates mornings.")
    make_call(migrated_url, employee)
    process(migrated_url)
    assert sql(migrated_url, "SELECT memory FROM leads") == "Lives in Hyderabad."
    assert "Lives in Hyderabad." not in fake.prompt() and "memory is off" in fake.prompt()


def test_without_an_llm_key_calls_are_skipped_not_filled_in(
    api: tuple[TestClient, Gemini], migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, fake = api
    employee, _ = setup(client, migrated_url)
    call = make_call(migrated_url, employee)
    monkeypatch.delenv("GEMINI_API_KEY")
    assert process(migrated_url) == 1
    assert row(migrated_url, call, "analysis_status") == "skipped"
    assert row(migrated_url, call, "summary") is None and row(migrated_url, call, "outcome") is None
    assert fake.requests == []
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")  # the key arrives later
    owner = {"Authorization": api[0].headers.get("Authorization", "")}
    assert owner is not None

    async def again(factory: Any) -> bool:
        async with factory() as session:
            found = await session.get(Call, call)
            assert found is not None
            ok = await postcall.reanalyze(session, found)
            await session.commit()
            return ok

    assert run_db(migrated_url, again) is True
    process(migrated_url)
    assert row(migrated_url, call, "analysis_status") == "done"


def test_unusable_output_and_vendor_errors_fail_the_analysis_visibly(
    api: tuple[TestClient, Gemini], migrated_url: str
) -> None:
    client, fake = api
    employee, _ = setup(client, migrated_url)
    broken = make_call(migrated_url, employee)
    fake.text = "I could not decide, sorry."
    process(migrated_url)
    assert row(migrated_url, broken, "analysis_status") == "failed"
    assert row(migrated_url, broken, "analysis_error") == "AnalysisError"
    assert row(migrated_url, broken, "outcome") is None
    outage = make_call(migrated_url, employee, phone="+919876543211")
    fake.status = 500
    process(migrated_url)
    assert row(migrated_url, outage, "analysis_status") == "failed"
    assert row(migrated_url, outage, "analysis_error") == "HTTPStatusError"


def test_a_call_nobody_spoke_on_is_a_no_conversation_without_asking_the_model(
    api: tuple[TestClient, Gemini], migrated_url: str
) -> None:
    client, fake = api
    employee, _ = setup(client, migrated_url)
    call = make_call(migrated_url, employee, [{"role": "assistant", "text": "Hello?"}])
    process(migrated_url)
    assert (
        row(migrated_url, call, "outcome") == "no_conversation"
        and row(migrated_url, call, "analysis_status") == "done"
    )
    assert fake.requests == []


def test_test_calls_and_calls_without_a_status_are_not_touched(
    api: tuple[TestClient, Gemini], migrated_url: str
) -> None:
    client, fake = api
    employee, _ = setup(client, migrated_url)
    untouched = make_call(migrated_url, employee)
    sql(migrated_url, "UPDATE calls SET analysis_status = NULL")
    assert process(migrated_url) == 0 and fake.requests == []
    assert row(migrated_url, untouched, "analysis_status") is None


def test_two_workers_analyse_each_call_once(
    api: tuple[TestClient, Gemini], migrated_url: str
) -> None:
    client, fake = api
    employee, _ = setup(client, migrated_url)
    for n in range(6):
        make_call(migrated_url, employee, phone=f"+91987654321{n}")

    async def work(factory: Any) -> list[int]:
        return list(
            await asyncio.gather(
                *(postcall.process_pending(factory, NOW, limit=3) for _ in range(4))
            )
        )

    done = run_db(migrated_url, work)
    assert sum(done) == 6 and len(fake.requests) == 6
    assert sql(migrated_url, "SELECT count(*) FROM calls WHERE analysis_status = 'done'") == 6


def test_unused_and_stuck_test_calls_are_reaped(
    api: tuple[TestClient, Gemini], migrated_url: str
) -> None:
    client, _ = api
    employee, _ = setup(client, migrated_url)
    account = sql(migrated_url, "SELECT account_id FROM employees")
    insert = (
        "INSERT INTO calls (account_id, employee_id, direction, channel, status, is_test,"
        " created_at, started_at)"
        " VALUES (:a, :e, 'inbound', 'instant', :s, true, :t, :t) RETURNING id"
    )
    old = NOW - timedelta(hours=3)
    unused = sql(migrated_url, insert, {"a": account, "e": employee, "s": "queued", "t": old})
    stuck = sql(migrated_url, insert, {"a": account, "e": employee, "s": "in_progress", "t": old})
    fresh = sql(
        migrated_url,
        insert,
        {"a": account, "e": employee, "s": "queued", "t": NOW - timedelta(minutes=1)},
    )
    running = sql(
        migrated_url,
        insert,
        {"a": account, "e": employee, "s": "in_progress", "t": NOW - timedelta(minutes=20)},
    )

    async def work(factory: Any) -> int:
        return await postcall.reap_test_calls(factory, NOW)

    assert run_db(migrated_url, work) == 2
    states = {
        str(c): row(migrated_url, str(c), "status::text") for c in (unused, stuck, fresh, running)
    }
    assert states == {
        str(unused): "canceled",
        str(stuck): "failed",
        str(fresh): "queued",
        str(running): "in_progress",
    }


def test_one_crashing_call_does_not_take_the_batch_with_it(
    api: tuple[TestClient, Gemini], migrated_url: str
) -> None:
    client, _fake = api
    employee, _ = setup(client, migrated_url)
    good1 = make_call(migrated_url, employee, phone="+919876543211")
    poison = make_call(migrated_url, employee, ["not a turn"], phone="+919876543212")  # type: ignore[list-item]
    good2 = make_call(migrated_url, employee, phone="+919876543213")
    assert process(migrated_url) == 3
    assert [row(migrated_url, c, "analysis_status") for c in (good1, poison, good2)] == [
        "done",
        "failed",
        "done",
    ]
    assert row(migrated_url, poison, "analysis_error") == "AttributeError"
    assert process(migrated_url) == 0  # nothing is picked up again and again


def test_no_lock_is_held_while_the_model_thinks(
    api: tuple[TestClient, Gemini], migrated_url: str
) -> None:
    """The claim is committed before the LLM call, so the call row can still be read and written."""
    import threading

    client, fake = api
    employee, _ = setup(client, migrated_url)
    call = make_call(migrated_url, employee)
    seen: dict[str, Any] = {}

    def spy(request: httpx.Request) -> httpx.Response:
        def probe() -> None:
            seen["status"] = row(migrated_url, call, "analysis_status")
            sql(migrated_url, "UPDATE calls SET duration_s = 99 WHERE id = :c", {"c": call})
            seen["wrote"] = True

        thread = threading.Thread(target=probe)
        thread.start()
        thread.join(timeout=5)  # a held row lock would make the update wait past this
        seen["blocked"] = thread.is_alive()
        return Gemini.handler(fake, request)

    transport = httpx.MockTransport(spy)
    import pytest as _pytest

    with _pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            common.VendorHealth,
            "client",
            lambda self, timeout=60.0: httpx.AsyncClient(transport=transport),
        )
        process(migrated_url)
    assert seen == {"status": "analysing", "wrote": True, "blocked": False}
    assert (
        row(migrated_url, call, "analysis_status") == "done"
        and row(migrated_url, call, "duration_s") == 99
    )


def test_a_claim_nobody_finished_is_taken_again_after_ten_minutes_but_not_before(
    api: tuple[TestClient, Gemini], migrated_url: str
) -> None:
    client, fake = api
    employee, _ = setup(client, migrated_url)
    call = make_call(migrated_url, employee, status="analysing")
    sql(
        migrated_url,
        "UPDATE calls SET analysis_started_at = :t WHERE id = :c",
        {"t": NOW - timedelta(minutes=3), "c": call},
    )
    assert process(migrated_url) == 0 and fake.requests == []  # another worker is on it
    sql(
        migrated_url,
        "UPDATE calls SET analysis_started_at = :t WHERE id = :c",
        {"t": NOW - timedelta(minutes=11), "c": call},
    )
    assert process(migrated_url) == 1
    assert row(migrated_url, call, "analysis_status") == "done"
