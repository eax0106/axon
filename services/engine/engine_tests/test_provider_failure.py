"""A leg with no vendor left ends the call cleanly: an apology in the call's language when a voice
still works, then the hang-up; an outgoing attempt that ended this way is tried again later."""

from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient
from tests.conftest import sql
from tests.helpers import add_call, add_lead, live_employee, seed, signup

from engine.call import APOLOGY

from .test_call import _Carrier, events
from .test_vobiz import START
from .vendors import Speaker, call, vendors, wire

__all__ = ["events", "vendors", "wire"]
CARRIER_ID = START["start"]["callId"]


def failure(events: list[dict[str, Any]]) -> dict[str, Any]:
    return next(e for e in events if e["type"] == "provider_failure")


def test_an_llm_with_nothing_left_apologises_then_hangs_up_once_it_was_heard(
    wire: Callable[..., dict[str, str]], events: list[dict[str, Any]]
) -> None:
    wire(backups=("stt", "tts"))
    sent = call(events)

    assert failure(events) == {"type": "provider_failure", "leg": "llm", "vendor": "badllm"}
    assert Speaker.said == [APOLOGY["en"]]
    assert any(m["event"] == "playAudio" for m in sent)
    assert any(m["event"] == "checkpoint" for m in sent)  # the hang-up waited for it to play
    assert _Carrier.hangups == [CARRIER_ID]
    assert events[-1] == {"type": "ended", "reason": "provider_failure"}


def test_the_apology_is_in_the_calls_language(
    wire: Callable[..., dict[str, str]], events: list[dict[str, Any]]
) -> None:
    wire(backups=("stt", "tts"))
    call(events, "?lang=te")
    assert Speaker.said == [APOLOGY["te"]]
    assert events[-1] == {"type": "ended", "reason": "provider_failure"}


def test_with_no_voice_left_the_call_is_hung_up_at_once(
    wire: Callable[..., dict[str, str]], events: list[dict[str, Any]]
) -> None:
    wire(backups=("stt", "llm"))
    call(events)

    assert failure(events)["leg"] == "tts"
    assert Speaker.said == []  # nothing could say it
    assert _Carrier.hangups == [CARRIER_ID]
    assert events[-1] == {"type": "ended", "reason": "provider_failure"}


def test_an_outgoing_attempt_that_ended_this_way_is_queued_again(
    db_client: TestClient,
    migrated_url: str,
    wire: Callable[..., dict[str, str]],
    events: list[dict[str, Any]],
) -> None:
    seed(migrated_url)
    owner = signup(db_client)
    employee = live_employee(db_client, migrated_url, owner)
    account = sql(migrated_url, "SELECT account_id FROM employees")
    lead = add_lead(migrated_url, account, "+919876543210", "Ravi")
    first = add_call(migrated_url, account, employee, lead, status="ringing")
    wire(backups=("stt", "tts"))
    call(events, f"?call={first}")

    assert sql(migrated_url, "SELECT status FROM calls WHERE id = :c", {"c": first}) == "failed"
    assert sql(migrated_url, "SELECT count(*) FROM calls") == 2
    queued = "SELECT {} FROM calls WHERE id <> :c"
    assert sql(migrated_url, queued.format("status"), {"c": first}) == "queued"
    assert sql(migrated_url, queued.format("attempt"), {"c": first}) == 2
    assert sql(migrated_url, queued.format("scheduled_for"), {"c": first}) is not None
    reason = "SELECT data->>'reason' FROM call_events WHERE type = 'ended'"
    assert sql(migrated_url, reason) == "provider_failure"
    failed = "SELECT count(*) FROM provider_outcomes WHERE vendor = 'badllm' AND NOT ok"
    assert sql(migrated_url, failed) == 1
