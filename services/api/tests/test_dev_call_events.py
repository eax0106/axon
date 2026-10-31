from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient

from .conftest import sql
from .developer_support import NOW, Receiver, events_of, make_webhook, tick
from .helpers import account_id, add_call, add_lead, live_employee, signup

CALLER = "+919876543210"
ALL = [
    "call.completed",
    "call.not_connected",
    "call.inbound_answered",
    "call.inbound_missed",
]


def setup(api: TestClient, url: str) -> tuple[dict[str, str], str, Any, Any]:
    owner = signup(api)
    employee = live_employee(api, url, owner)
    account = account_id(api, owner)
    return owner, employee, account, add_lead(url, account, CALLER, "Asha")


def ended(**cols: Any) -> dict[str, Any]:
    return {
        "created_at": NOW - timedelta(minutes=3),
        "ended_at": NOW - timedelta(minutes=1),
        **cols,
    }


def test_an_answered_outgoing_call_is_announced_once_after_its_analysis(
    api: TestClient, migrated_url: str
) -> None:
    _, employee, account, lead = setup(api, migrated_url)
    call = add_call(
        migrated_url, account, employee, lead,
        **ended(answered_at=NOW - timedelta(minutes=3), duration_s=120, analysis_status="pending"),
    )  # fmt: skip
    assert tick(migrated_url) == 0 and events_of(migrated_url) == []  # waits for the analysis

    sql(
        migrated_url,
        "UPDATE calls SET analysis_status = 'done', outcome = 'interested', sentiment = 'positive',"
        " summary = 'Wants a visit', captured = '{\"budget\": \"80 lakh\"}' WHERE id = :i",
        {"i": call},
    )
    tick(migrated_url)
    tick(migrated_url)  # a second look finds nothing new
    (event,) = events_of(migrated_url)
    assert event["type"] == "call.completed" and str(event["employee_id"]) == employee
    shown = event["data"]["call"]
    assert shown["id"] == str(call) and shown["phone"] == CALLER and shown["duration_s"] == 120
    assert shown["outcome"] == "interested" and shown["summary"] == "Wants a visit"
    assert shown["captured"] == {"budget": "80 lakh"} and shown["voicemail"] is False
    assert "transcript" not in shown
    assert sql(
        migrated_url, "SELECT events_emitted_at IS NOT NULL FROM calls WHERE id = :i", {"i": call}
    )


def test_an_outgoing_attempt_nobody_answered_is_announced_at_once(
    api: TestClient, migrated_url: str
) -> None:
    _, employee, account, lead = setup(api, migrated_url)
    for status in ("no_answer", "busy", "failed"):
        add_call(migrated_url, account, employee, lead, **ended(status=status, attempt=2))
    tick(migrated_url)
    found = events_of(migrated_url, "call.not_connected")
    assert len(found) == 3 and len(events_of(migrated_url)) == 3
    assert sorted(e["data"]["call"]["status"] for e in found) == ["busy", "failed", "no_answer"]
    assert (
        found[0]["data"]["call"]["attempt"] == 2 and found[0]["data"]["call"]["answered_at"] is None
    )


def test_incoming_calls_are_answered_or_missed_with_the_callers_number_and_reason(
    api: TestClient, migrated_url: str
) -> None:
    _, employee, account, lead = setup(api, migrated_url)
    answered = add_call(
        migrated_url, account, employee, lead,
        **ended(direction="inbound", channel="inbound", answered_at=NOW, analysis_status="done"),
    )  # fmt: skip
    missed = add_call(
        migrated_url, account, employee, None,
        **ended(direction="inbound", channel="inbound", status="no_answer"),
    )  # fmt: skip
    sql(
        migrated_url,
        "UPDATE calls SET caller_phone = '+919000000009', miss_reason = 'the business was closed'"
        " WHERE id = :i",
        {"i": missed},
    )
    tick(migrated_url)
    (yes,) = events_of(migrated_url, "call.inbound_answered")
    (no,) = events_of(migrated_url, "call.inbound_missed")
    assert yes["data"]["call"]["id"] == str(answered) and yes["data"]["call"]["phone"] == CALLER
    assert no["data"]["call"]["id"] == str(missed)
    assert no["data"]["call"]["phone"] == "+919000000009"
    assert no["data"]["call"]["miss_reason"] == "the business was closed"


def test_test_calls_and_calls_that_never_finished_or_never_dialed_are_not_announced(
    api: TestClient, migrated_url: str
) -> None:
    _, employee, account, lead = setup(api, migrated_url)
    add_call(migrated_url, account, employee, lead, **ended(is_test=True, answered_at=NOW))
    for status in ("queued", "ringing", "in_progress"):
        add_call(migrated_url, account, employee, lead, status=status, created_at=NOW)
    add_call(migrated_url, account, employee, lead, **ended(status="canceled"))
    assert tick(migrated_url) == 0 and events_of(migrated_url) == []


def test_a_call_whose_analysis_never_comes_goes_out_after_the_wait_without_it(
    api: TestClient, migrated_url: str
) -> None:
    _, employee, account, lead = setup(api, migrated_url)
    waiting = add_call(
        migrated_url, account, employee, lead,
        **ended(answered_at=NOW - timedelta(minutes=9), analysis_status="pending"),
    )  # fmt: skip
    stuck = add_call(
        migrated_url, account, employee, lead,
        created_at=NOW - timedelta(hours=1),
        ended_at=NOW - timedelta(minutes=21),
        answered_at=NOW - timedelta(minutes=50),
        analysis_status="pending",
    )  # fmt: skip
    tick(migrated_url)
    (event,) = events_of(migrated_url)
    assert event["data"]["call"]["id"] == str(stuck) and event["data"]["call"]["summary"] is None
    assert (
        sql(migrated_url, "SELECT events_emitted_at FROM calls WHERE id = :i", {"i": waiting})
        is None
    )


def test_a_call_whose_analysis_was_skipped_or_failed_is_announced_without_a_summary(
    api: TestClient, migrated_url: str
) -> None:
    _, employee, account, lead = setup(api, migrated_url)
    for state in ("skipped", "failed"):
        add_call(
            migrated_url, account, employee, lead,
            **ended(answered_at=NOW - timedelta(minutes=3), analysis_status=state),
        )  # fmt: skip
    tick(migrated_url)
    found = events_of(migrated_url, "call.completed")
    assert len(found) == 2 and all(e["data"]["call"]["summary"] is None for e in found)


def test_a_subscribed_endpoint_is_sent_each_kind_with_its_type(
    api: TestClient, receiver: type[Receiver], migrated_url: str
) -> None:
    owner, employee, account, lead = setup(api, migrated_url)
    make_webhook(api, owner, receiver.base + "/hook", ALL)
    add_call(
        migrated_url, account, employee, lead, **ended(answered_at=NOW, analysis_status="done")
    )
    add_call(migrated_url, account, employee, lead, **ended(status="no_answer"))
    add_call(
        migrated_url, account, employee, lead,
        **ended(direction="inbound", channel="inbound", answered_at=NOW, analysis_status="done"),
    )  # fmt: skip
    add_call(
        migrated_url, account, employee, lead,
        **ended(direction="inbound", channel="inbound", status="no_answer"),
    )  # fmt: skip
    tick(migrated_url)
    assert sorted(b["type"] for b in receiver.bodies()) == sorted(ALL)


def test_a_real_dial_and_the_carriers_report_announce_the_attempt_that_did_not_connect(
    api: TestClient, carrier: Any, migrated_url: str
) -> None:
    from . import dialing
    from .campaigning import end_call

    fake, adapter = carrier
    owner = signup(api)
    employee = live_employee(api, migrated_url, owner)
    result = dialing.lead_in(migrated_url, employee, "+919876500001")
    dialing.tick(migrated_url, adapter, NOW)
    assert tick(migrated_url) == 0 or events_of(migrated_url, "call.not_connected") == []
    end_call(migrated_url, fake, adapter, result.call_id, NOW + timedelta(minutes=1))
    tick(migrated_url)
    (event,) = events_of(migrated_url, "call.not_connected")
    shown = event["data"]["call"]
    assert shown["id"] == str(result.call_id) and shown["status"] == "busy"
    assert shown["phone"] == "+919876500001" and shown["attempt"] == 1
    assert len(events_of(migrated_url, "call.not_connected")) == 1  # the retry is only queued


def test_the_scan_reads_an_index_that_leaves_out_test_and_cancelled_calls(
    api: TestClient, migrated_url: str
) -> None:
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.developer import settle

    def plan(query: str) -> str:
        async def explain() -> str:
            engine = create_async_engine(migrated_url)
            try:
                async with engine.connect() as conn:
                    await conn.execute(text("SET enable_seqscan = off"))  # force a choice
                    # On a near-empty table the planner may pick any other index whose costs
                    # tie (it did on CI). Drop the others for this transaction only, so the plan
                    # shows whether this index can serve the query at all.
                    others = await conn.execute(
                        text(
                            "SELECT indexname FROM pg_indexes WHERE tablename = 'calls'"
                            " AND indexname <> 'ix_calls_unannounced' AND indexname NOT IN"
                            " (SELECT conname FROM pg_constraint"
                            " WHERE conrelid = 'calls'::regclass)"
                        )
                    )
                    for (name,) in list(others):
                        await conn.execute(text(f'DROP INDEX "{name}"'))
                    found = await conn.execute(text("EXPLAIN " + query))
                    lines = "\n".join(row[0] for row in found)
                    await conn.rollback()
                    return lines
            finally:
                await engine.dispose()

        return asyncio.run(explain())

    ready = settle.ready(NOW).compile(compile_kwargs={"literal_binds": True})
    assert "ix_calls_unannounced" in plan(str(ready))
    everything_ended = (
        "SELECT * FROM calls WHERE events_emitted_at IS NULL AND ended_at IS NOT NULL"
    )
    assert "ix_calls_unannounced" not in plan(everything_ended)  # the index is narrower than that
    definition = sql(
        migrated_url, "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_calls_unannounced'"
    )
    assert "NOT is_test" in definition and "canceled" not in definition
