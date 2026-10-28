"""The engine writes each call's row: pickup, transcript, duration, final status, events."""

import asyncio
import json
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.websockets import WebSocketDisconnect
from tests.conftest import sql
from tests.helpers import add_call, add_lead, live_employee, seed, signup

import engine.main
from engine.call import CallSettings
from engine.main import app
from engine.records import MAX_EVENTS, CallRecorder, TranscriptBuilder

from .test_call import SILENCE_ULAW, _Carrier, events, providers  # noqa: F401
from .test_vobiz import START

CARRIER_ID = START["start"]["callId"]


def build(*feed: dict[str, Any]) -> list[dict[str, Any]]:
    builder = TranscriptBuilder()
    for event in feed:
        builder.feed(event)
    return builder.turns()


def texts(turns: list[dict[str, Any]]) -> list[tuple[str, str]]:
    return [(t["role"], t["text"]) for t in turns]


def test_the_agents_words_are_gathered_until_it_stops_speaking() -> None:
    turns = build(
        {"type": "bot_started_speaking"},
        {"type": "bot_text", "text": "Hello"},
        {"type": "bot_text", "text": "this is"},
        {"type": "bot_text", "text": "Asha."},
        {"type": "bot_stopped_speaking"},
        {"type": "user_transcript", "text": " Hi,   who is   this? "},
        {"type": "bot_text", "text": "Asha from SunBright."},
        {"type": "ended"},
    )
    assert texts(turns) == [
        ("assistant", "Hello this is Asha."),
        ("user", "Hi, who is this?"),
        ("assistant", "Asha from SunBright."),
    ]
    assert all(t["at"] for t in turns)


def test_an_interrupted_agent_turn_keeps_what_was_said_and_empty_events_are_ignored() -> None:
    turns = build(
        {"type": "bot_text", "text": "Let me explain our"},
        {"type": "interruption"},
        {"type": "user_transcript", "text": "   "},
        {"type": "user_transcript", "text": "Stop, how much?"},
        {"type": "bot_text", "text": ""},
        {"type": "usage", "duration_s": 1},
    )
    assert texts(turns) == [("assistant", "Let me explain our"), ("user", "Stop, how much?")]
    assert build() == []


def fetch(url: str, call: Any) -> dict[str, Any]:
    from sqlalchemy import text

    async def work(db: Any) -> dict[str, Any]:
        async with db.connect() as conn:
            result = await conn.execute(text("SELECT * FROM calls WHERE id = :c"), {"c": call})
            return dict(result.mappings().one())

    return with_db(url, work)  # type: ignore[no-any-return]


def event_types(url: str, call: Any) -> list[str]:
    from sqlalchemy import text

    async def work(db: Any) -> list[str]:
        async with db.connect() as conn:
            rows = await conn.execute(
                text("SELECT type FROM call_events WHERE call_id = :c ORDER BY id"), {"c": call}
            )
            return [r[0] for r in rows]

    return with_db(url, work)  # type: ignore[no-any-return]


def with_db(url: str, work: Any) -> Any:
    async def go() -> Any:
        db = create_async_engine(url)
        try:
            return await work(db)
        finally:
            await db.dispose()

    return asyncio.run(go())


@pytest.fixture
def world(db_client: TestClient, migrated_url: str) -> tuple[str, Any, Any]:
    seed(migrated_url)
    owner = signup(db_client)
    employee = live_employee(db_client, migrated_url, owner)
    account = sql(migrated_url, "SELECT account_id FROM employees")
    return migrated_url, employee, account


def new_call(world: tuple[str, Any, Any], **cols: Any) -> uuid.UUID:
    url, employee, account = world
    lead = (
        add_lead(url, account, "+919876543210", "Ravi")
        if not sql(url, "SELECT 1 FROM leads")
        else sql(url, "SELECT id FROM leads")
    )
    return uuid.UUID(str(add_call(url, account, employee, lead, **{"status": "ringing", **cols})))


def recorder(url: str, call: uuid.UUID, work: Any) -> Any:
    async def go(db: Any) -> Any:
        return await work(CallRecorder(db, call))

    return with_db(url, go)


def test_pickup_moves_a_waiting_call_to_in_progress(world: tuple[str, Any, Any]) -> None:
    url = world[0]
    call = new_call(world)
    recorder(url, call, lambda r: r.started())
    got = fetch(url, call)
    assert got["status"] == "in_progress" and got["answered_at"] and got["started_at"]


def test_pickup_only_touches_the_row_that_belongs_to_this_carrier_call(
    world: tuple[str, Any, Any],
) -> None:
    url = world[0]
    mine, other = new_call(world), new_call(world)
    sql(url, "UPDATE calls SET carrier_call_id = 'req-1' WHERE id = :c", {"c": mine})
    sql(url, "UPDATE calls SET carrier_call_id = 'someone-else' WHERE id = :c", {"c": other})
    recorder(url, other, lambda r: r.started("req-1"))
    recorder(url, mine, lambda r: r.started("req-1"))
    assert fetch(url, other)["status"] == "ringing" and fetch(url, mine)["status"] == "in_progress"
    unset = new_call(world)  # the dialer had not stored the carrier id yet
    recorder(url, unset, lambda r: r.started("req-9"))
    assert fetch(url, unset)["status"] == "in_progress"


def test_finishing_writes_transcript_duration_status_recording_and_marks_it_for_analysis(
    world: tuple[str, Any, Any],
) -> None:
    url = world[0]
    call = new_call(world, status="in_progress")

    async def work(r: CallRecorder) -> None:
        await r.started()
        r.tap({"type": "user_transcript", "text": "Hello"})
        r.tap({"type": "bot_text", "text": "Hi there"})
        r.tap({"type": "interruption"})
        r.tap({"type": "bot_stopped_speaking"})
        r.tap({"type": "usage", "duration_s": 3.2})
        await r.finished("caller_hung_up", "recordings/x.wav")

    recorder(url, call, work)
    got = fetch(url, call)
    assert (got["status"], got["recording_key"], got["analysis_status"]) == (
        "completed",
        "recordings/x.wav",
        "pending",
    )
    assert got["ended_at"] and got["duration_s"] is not None and got["duration_s"] >= 0
    assert [(t["role"], t["text"]) for t in got["transcript"]] == [
        ("user", "Hello"),
        ("assistant", "Hi there"),
    ]
    assert event_types(url, call) == ["interruption", "usage", "ended"]
    assert (
        sql(url, "SELECT data->>'reason' FROM call_events WHERE type = 'ended'") == "caller_hung_up"
    )


@pytest.mark.parametrize(
    ("reason", "status"),
    [
        ("agent_ended", "completed"),
        ("max_length", "completed"),
        ("silence", "completed"),
        ("ConnectionResetError", "failed"),
    ],
)
def test_the_reason_decides_completed_or_failed(
    world: tuple[str, Any, Any], reason: str, status: str
) -> None:
    url = world[0]
    call = new_call(world, status="in_progress")
    recorder(url, call, lambda r: r.finished(reason, None))
    assert fetch(url, call)["status"] == status


def test_test_calls_are_not_queued_for_analysis(world: tuple[str, Any, Any]) -> None:
    url = world[0]
    test = new_call(world, status="in_progress", is_test=True)
    recorder(url, test, lambda r: r.finished("caller_hung_up", None))
    assert fetch(url, test)["analysis_status"] is None and fetch(url, test)["status"] == "completed"


def test_the_carriers_callback_settling_the_call_first_does_not_lose_the_transcript(
    world: tuple[str, Any, Any],
) -> None:
    """Vobiz calls back as soon as the caller hangs up, usually before the engine has uploaded the
    recording and written the record. The callback's status stands; the engine's data is added."""
    url = world[0]
    call = new_call(world, status="in_progress")

    async def work(db: Any) -> None:
        from sqlalchemy import text

        r = CallRecorder(db, call)
        r.tap({"type": "user_transcript", "text": "Please call me tomorrow"})
        async with db.begin() as conn:  # the callback settles the call first
            await conn.execute(
                text(
                    "UPDATE calls SET status = 'completed', ended_at = now(), duration_s = 77"
                    " WHERE id = :c"
                ),
                {"c": call},
            )
        await r.finished("caller_hung_up", "recordings/late.wav")

    with_db(url, work)
    got = fetch(url, call)
    assert (
        got["status"] == "completed" and got["duration_s"] == 77
    )  # the callback's values are kept
    assert got["recording_key"] == "recordings/late.wav" and got["analysis_status"] == "pending"
    assert [t["text"] for t in got["transcript"]] == ["Please call me tomorrow"]
    assert event_types(url, call)[-1] == "ended"


def test_a_busy_or_failed_call_that_never_had_a_session_is_still_just_a_record(
    world: tuple[str, Any, Any],
) -> None:
    url = world[0]
    call = new_call(world, status="busy")
    recorder(url, call, lambda r: r.finished("caller_hung_up", None))
    got = fetch(url, call)
    assert got["status"] == "busy" and got["transcript"] == [] and got["recording_key"] is None


def test_a_call_already_analysed_is_not_sent_back_to_the_queue(world: tuple[str, Any, Any]) -> None:
    url = world[0]
    call = new_call(world, status="completed", analysis_status="done")
    recorder(url, call, lambda r: r.finished("caller_hung_up", "recordings/z.wav"))
    assert fetch(url, call)["analysis_status"] == "done"


def test_pickup_is_recorded_when_the_stream_names_the_call_by_its_own_id(
    world: tuple[str, Any, Any],
) -> None:
    """The dialer stores the dial request's id; the stream and the callback carry the call's id."""
    url = world[0]
    call = new_call(world)
    sql(
        url,
        "UPDATE calls SET carrier_call_id = 'req-1', carrier_leg_id = 'leg-1' WHERE id = :c",
        {"c": call},
    )
    recorder(url, call, lambda r: r.started("leg-1"))
    got = fetch(url, call)
    assert got["status"] == "in_progress" and got["answered_at"] is not None
    stranger = new_call(world)
    sql(
        url,
        "UPDATE calls SET carrier_call_id = 'req-2', carrier_leg_id = 'leg-2' WHERE id = :c",
        {"c": stranger},
    )
    recorder(url, stranger, lambda r: r.started("leg-1"))
    assert fetch(url, stranger)["status"] == "ringing"
    # And it remembers the call's id for the callback when the dialer had only the request id.
    fresh = new_call(world)
    recorder(url, fresh, lambda r: r.started("leg-5"))
    assert fetch(url, fresh)["carrier_leg_id"] == "leg-5"


def test_the_event_list_is_capped(world: tuple[str, Any, Any]) -> None:
    url = world[0]
    call = new_call(world, status="in_progress")

    async def work(r: CallRecorder) -> None:
        for _ in range(MAX_EVENTS + 100):
            r.tap({"type": "interruption"})
        await r.finished("caller_hung_up", None)

    recorder(url, call, work)
    assert len(event_types(url, call)) == MAX_EVENTS + 1  # the capped events and the final `ended`


def test_a_call_whose_setup_failed_is_closed_not_left_in_progress(
    world: tuple[str, Any, Any],
) -> None:
    url = world[0]
    call = new_call(world, status="in_progress", is_test=True)
    recorder(url, call, lambda r: r.abandon("provider_not_configured"))
    got = fetch(url, call)
    assert got["status"] == "failed" and got["ended_at"]
    assert (
        sql(url, "SELECT data->>'reason' FROM call_events WHERE type = 'setup_failed'")
        == "provider_not_configured"
    )


def run_call(monkeypatch: pytest.MonkeyPatch, call_id: Any, events_: list[dict[str, Any]]) -> None:
    monkeypatch.setattr(
        engine.main,
        "CallSettings",
        lambda language: CallSettings(language=language, max_call_s=2.0, silence_timeout_s=60.0),
    )
    with (
        TestClient(app) as client,
        client.websocket_connect(f"/vobiz/stream?lang=te&call={call_id}") as ws,
    ):
        ws.send_text(json.dumps(START))
        for _ in range(50):
            ws.send_text(json.dumps({"event": "media", "media": {"payload": SILENCE_ULAW}}))
        try:
            while True:
                ws.receive_text()
        except WebSocketDisconnect:
            pass
        deadline = time.monotonic() + 10
        while not (events_ and events_[-1]["type"] == "ended") and time.monotonic() < deadline:
            time.sleep(0.05)
        time.sleep(0.5)  # the record is written just after the last live event


def test_a_whole_call_through_the_engine_leaves_its_row_finished(
    db_client: TestClient,
    migrated_url: str,
    providers: None,  # noqa: F811
    events: list[dict[str, Any]],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed(migrated_url)
    owner = signup(db_client)
    employee = live_employee(db_client, migrated_url, owner)
    account = sql(migrated_url, "SELECT account_id FROM employees")
    lead = add_lead(migrated_url, account, "+919876543210", "Ravi")
    call = add_call(migrated_url, account, employee, lead, status="ringing")
    run_call(monkeypatch, call, events)
    got = fetch(migrated_url, call)
    assert got["status"] == "completed" and got["answered_at"] and got["ended_at"]
    assert got["duration_s"] is not None and 1 <= got["duration_s"] <= 5
    assert got["analysis_status"] == "pending"
    assert event_types(migrated_url, call)[0] == "usage" or "ended" in event_types(
        migrated_url, call
    )
    assert event_types(migrated_url, call)[-1] == "ended"
    assert datetime.now(UTC) > got["ended_at"]


def test_vendor_outcomes_feed_the_health_score(world: tuple[str, Any, Any]) -> None:
    url = world[0]
    call = new_call(world)

    async def work(r: CallRecorder) -> None:
        await r.started()
        await r.vendor_failed("tts", "cartesia")  # the call failed over and left it behind
        await r.finished("agent_ended", None, {"stt": "sarvam", "llm": "gemini", "tts": "sarvam"})

    recorder(url, call, work)
    outcomes = sql(
        url,
        "SELECT string_agg(kind || ':' || vendor || ':' || ok, ',' ORDER BY kind, vendor)"
        " FROM provider_outcomes",
    )
    assert outcomes == "llm:gemini:true,stt:sarvam:true,tts:cartesia:false,tts:sarvam:true"
