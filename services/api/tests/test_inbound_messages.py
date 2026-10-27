"""What a caller leaves (a message, a call-back request) becomes a task for the owner."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

from app.inbound import messages
from app.models import Call

from .conftest import sql
from .helpers import run_db, signup
from .inbound_support import inbound_employee
from .test_post_call_job import (  # noqa: F401 - fixtures
    NOW,
    TURNS,
    Gemini,
    api,
    model_reply,
    own_notes,
    process,
)

QUOTE = "my budget is around five lakh rupees"
NO_CALLBACK = {"at": None, "quote": None}


def inbound_call(url: str, employee: str, turns: list[dict[str, Any]] = TURNS) -> str:
    """A finished incoming call, waiting for its analysis, from a caller we know."""
    account = sql(url, "SELECT account_id FROM employees WHERE id = :e", {"e": employee})
    lead = sql(
        url,
        "INSERT INTO leads (account_id, phone, name) VALUES (:a, '+919876543210', 'Ravi')"
        " RETURNING id",
        {"a": account},
    )
    call = sql(
        url,
        "INSERT INTO calls (account_id, employee_id, lead_id, direction, channel, status, ended_at,"
        " caller_phone, transcript, analysis_status) VALUES (:a, :e, :l, 'inbound', 'inbound',"
        " 'completed', now(), '+919876543210', CAST(:t AS jsonb), 'pending') RETURNING id",
        {"a": account, "e": employee, "l": lead, "t": json.dumps(turns)},
    )
    return str(call)


def stored(url: str) -> list[dict[str, Any]]:
    async def work(factory: Any) -> list[dict[str, Any]]:
        from sqlalchemy import text

        async with factory() as session:
            rows = await session.execute(text("SELECT * FROM inbound_messages ORDER BY created_at"))
            return [dict(r._mapping) for r in rows]

    out: list[dict[str, Any]] = run_db(url, work)
    return out


def test_what_the_caller_asks_to_pass_on_becomes_a_message_and_rings_the_bell(
    api: tuple[TestClient, Gemini],  # noqa: F811
    migrated_url: str,
) -> None:
    client, fake = api
    fake.text = model_reply(
        message={"text": "Wants a quote for a five lakh budget.", "quote": QUOTE}
    )
    employee, owner = inbound_employee(client, migrated_url)
    call = inbound_call(migrated_url, employee)
    assert process(migrated_url) == 1
    (message,) = stored(migrated_url)
    assert message["body"] == "Wants a quote for a five lakh budget."
    assert str(message["call_id"]) == call and message["phone"] == "+919876543210"
    assert message["name"] == "Ravi" and message["done_at"] is None
    assert message["callback_at"] is not None  # the model also found a call-back time
    assert "inbound_message" in [n["kind"] for n in own_notes(client, owner)]


def test_a_callback_request_alone_is_a_message_saying_when(
    api: tuple[TestClient, Gemini],  # noqa: F811
    migrated_url: str,
) -> None:
    client, _ = api
    employee, _owner = inbound_employee(client, migrated_url)
    inbound_call(migrated_url, employee)
    process(migrated_url)
    (message,) = stored(migrated_url)
    assert message["body"] == "Asked to be called back: 03 Nov, 18:00 IST."


def test_a_message_the_caller_never_said_is_not_written_for_them(
    api: tuple[TestClient, Gemini],  # noqa: F811
    migrated_url: str,
) -> None:
    client, fake = api
    fake.text = model_reply(
        message={"text": "Wants a free solar panel.", "quote": "give me one for free"},
        callback=NO_CALLBACK,
    )
    employee, _owner = inbound_employee(client, migrated_url)
    inbound_call(migrated_url, employee)
    process(migrated_url)
    assert stored(migrated_url) == []


def test_a_call_we_made_leaves_no_message(
    api: tuple[TestClient, Gemini],  # noqa: F811
    migrated_url: str,
) -> None:
    client, fake = api
    fake.text = model_reply(message={"text": "Wants a quote.", "quote": QUOTE})
    employee, _owner = inbound_employee(client, migrated_url)
    call = inbound_call(migrated_url, employee)
    sql(migrated_url, "UPDATE calls SET direction = 'outbound' WHERE id = :c", {"c": call})
    process(migrated_url)
    assert stored(migrated_url) == []


def test_someone_who_asked_not_to_be_called_leaves_no_task_to_call_them(
    api: tuple[TestClient, Gemini],  # noqa: F811
    migrated_url: str,
) -> None:
    client, fake = api
    fake.text = model_reply(
        message={"text": "Wants a quote.", "quote": QUOTE},
        do_not_call={"requested": True, "quote": "Yes. I am in Hyderabad"},
    )
    employee, _owner = inbound_employee(client, migrated_url)
    inbound_call(migrated_url, employee)
    process(migrated_url)
    assert stored(migrated_url) == []


def test_a_call_has_one_message_whatever_order_its_parts_arrive_in(
    api: tuple[TestClient, Gemini],  # noqa: F811
    migrated_url: str,
) -> None:
    client, _ = api
    employee, _owner = inbound_employee(client, migrated_url)
    call = inbound_call(migrated_url, employee)

    async def add(factory: Any, body: str) -> None:
        async with factory() as session:
            record = await session.get(Call, uuid.UUID(call))
            await messages.add(session, record, body, None, None, datetime.now(UTC))
            await session.commit()

    for body in ("Wants a quote.", "Asked to speak to a person.", "Wants a quote."):
        run_db(migrated_url, lambda f, b=body: add(f, b))
    (message,) = stored(migrated_url)
    assert message["body"] == "Wants a quote.\nAsked to speak to a person."
    bells = sql(migrated_url, "SELECT count(*) FROM notifications WHERE kind = 'inbound_message'")
    assert bells == 1


def leave_messages(url: str, employee: str, count: int = 2) -> list[str]:
    """`count` messages from `count` incoming calls to the employee, oldest first."""
    account = sql(url, "SELECT account_id FROM employees WHERE id = :e", {"e": employee})
    ids = []
    for index in range(count):
        call = sql(
            url,
            "INSERT INTO calls (account_id, employee_id, direction, channel, status, caller_phone)"
            " VALUES (:a, :e, 'inbound', 'inbound', 'completed', '+919876543210') RETURNING id",
            {"a": account, "e": employee},
        )
        message = sql(
            url,
            "INSERT INTO inbound_messages (account_id, employee_id, call_id, phone, body,"
            " created_at) VALUES (:a, :e, :c, '+919876543210', :b, now() + make_interval("
            "secs => :n)) RETURNING id",
            {"a": account, "e": employee, "c": call, "b": f"message {index}", "n": index},
        )
        ids.append(str(message))
    return ids


def bodies(client: TestClient, owner: dict[str, str], **query: str) -> list[str]:
    response = client.get("/inbound/messages", params=query, headers=owner)
    assert response.status_code == 200, response.text
    return [m["body"] for m in response.json()["items"]]


def test_messages_are_listed_open_first_and_newest_first(
    api: tuple[TestClient, Gemini],  # noqa: F811
    migrated_url: str,
) -> None:
    client, _ = api
    employee, owner = inbound_employee(client, migrated_url)
    first, _second = leave_messages(migrated_url, employee)
    assert bodies(client, owner) == ["message 1", "message 0"]
    assert client.post(f"/inbound/messages/{first}/done", headers=owner).json()["done"] is True
    assert bodies(client, owner) == ["message 1"]
    assert bodies(client, owner, state="done") == ["message 0"]
    assert bodies(client, owner, state="all") == ["message 1", "message 0"]
    reopened = client.post(f"/inbound/messages/{first}/reopen", headers=owner).json()
    assert reopened["done"] is False and reopened["done_at"] is None
    assert bodies(client, owner, state="done") == []
    total = client.get("/inbound/messages", params={"limit": 1}, headers=owner).json()["total"]
    assert total == 2


def test_the_list_can_be_narrowed_to_one_employee(
    api: tuple[TestClient, Gemini],  # noqa: F811
    migrated_url: str,
) -> None:
    client, _ = api
    employee, owner = inbound_employee(client, migrated_url)
    leave_messages(migrated_url, employee)
    other = uuid.uuid4()
    assert bodies(client, owner, employee_id=str(other)) == []
    assert len(bodies(client, owner, employee_id=employee)) == 2


def test_nobody_sees_or_ticks_another_accounts_messages(
    api: tuple[TestClient, Gemini],  # noqa: F811
    migrated_url: str,
) -> None:
    client, _ = api
    employee, _owner = inbound_employee(client, migrated_url)
    (message,) = leave_messages(migrated_url, employee, 1)
    stranger = signup(client, "other@example.com", "Other")
    assert bodies(client, stranger, state="all") == []
    assert client.post(f"/inbound/messages/{message}/done", headers=stranger).status_code == 404
    assert client.post(f"/inbound/messages/{message}/reopen", headers=stranger).status_code == 404
    assert sql(migrated_url, "SELECT done_at FROM inbound_messages") is None
    assert client.get("/inbound/messages").status_code == 401


def test_a_callback_asked_for_on_a_bulk_employees_incoming_call_is_a_message_not_a_stuck_call(
    api: tuple[TestClient, Gemini],  # noqa: F811
    migrated_url: str,
) -> None:
    """Nothing dials a Bulk employee's own call-back, so a queued call would sit there for ever and
    block the lead's later requests: the message task carries the request instead."""
    client, _ = api
    employee, _owner = inbound_employee(client, migrated_url, channel="bulk")
    inbound_call(migrated_url, employee)
    sql(migrated_url, "UPDATE calls SET channel = 'bulk'")
    process(migrated_url)
    assert sql(migrated_url, "SELECT count(*) FROM calls WHERE status = 'queued'") == 0
    (message,) = stored(migrated_url)
    assert message["callback_at"] is not None
