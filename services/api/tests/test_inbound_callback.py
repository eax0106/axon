"""The call back to a caller we could not answer: one, in hours, never against a refusal."""

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.instant import dialer
from app.models import Call, CallStatus
from app.providers.telephony.vobiz import VobizTelephony

from .conftest import sql
from .dialing import Carrier, tick
from .helpers import run_db
from .inbound_support import CALLER, NOW, NUMBER, calls, events, inbound_employee, ring

CLOSED = {
    "always_open": False,
    "hours": [{"days": [1], "start_min": 540, "end_min": 1020}],  # Tuesdays only: Monday is shut
    "closed_mode": "hang_up",
}


@pytest.fixture(autouse=True)
def public_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AXON_ENGINE_PUBLIC_URL", "https://engine.example.in")
    monkeypatch.setenv("AXON_API_PUBLIC_URL", "https://api.example.in")


def call_backs(url: str) -> list[dict[str, Any]]:
    return calls(url, "is_callback")


def test_a_caller_who_found_the_line_shut_is_called_back_once_inside_calling_hours(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    employee, _owner = inbound_employee(api, migrated_url, settings=CLOSED)
    missed = ring(migrated_url, fake, carrier_id="leg-1")
    assert missed.kind == "missed" and missed.code == "closed"
    (back,) = call_backs(migrated_url)
    assert back["status"] == "queued" and back["direction"] == "outbound"
    assert str(back["employee_id"]) == employee and back["callback_of_id"] == missed.call_id
    assert back["scheduled_for"] == NOW + timedelta(minutes=1)  # 11:01 IST: inside 9 to 9
    assert "auto_callback_scheduled" in [t for t, _ in events(migrated_url, missed.call_id)]


def test_a_caller_who_found_every_channel_busy_is_called_back_too(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    inbound_employee(api, migrated_url)
    ring(migrated_url, fake, carrier_id="leg-1", caller="+919876543211")
    assert ring(migrated_url, fake, carrier_id="leg-2").code == "busy"
    (back,) = call_backs(migrated_url)
    assert back["status"] == "queued"


@pytest.mark.parametrize(
    "change",
    [
        "UPDATE employees SET status = 'paused'",
        "UPDATE accounts SET credit_balance = 0",
    ],
)
def test_a_caller_the_employee_could_not_serve_for_other_reasons_is_not_called_back(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None], change: str
) -> None:
    fake, _ = carrier
    inbound_employee(api, migrated_url)
    sql(migrated_url, change)
    assert ring(migrated_url, fake).kind == "missed"
    assert call_backs(migrated_url) == []


def test_with_the_switch_off_nobody_is_called_back(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    inbound_employee(api, migrated_url, settings={**CLOSED, "auto_callback": False})
    assert ring(migrated_url, fake).kind == "missed"
    assert call_backs(migrated_url) == []


def test_a_number_on_the_do_not_call_list_is_not_called_back_and_the_timeline_says_why(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    inbound_employee(api, migrated_url, settings=CLOSED)
    account = sql(migrated_url, "SELECT account_id FROM employees")
    sql(
        migrated_url,
        "INSERT INTO dnc_entries (account_id, phone, source) VALUES (:a, :p, 'manual')",
        {"a": account, "p": CALLER},
    )
    missed = ring(migrated_url, fake)
    assert call_backs(migrated_url) == []
    assert ("auto_callback_skipped", {"reason": "the number is on the do-not-call list"}) in events(
        migrated_url, missed.call_id
    )


def test_a_withheld_number_cannot_be_called_back(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    inbound_employee(api, migrated_url, settings=CLOSED)
    missed = ring(migrated_url, fake, caller="anonymous")
    assert call_backs(migrated_url) == []
    skipped = [d for t, d in events(migrated_url, missed.call_id) if t == "auto_callback_skipped"]
    assert skipped == [{"reason": "the caller's number cannot be called back"}]


def test_a_caller_is_called_back_once_a_day_however_often_they_ring(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    inbound_employee(api, migrated_url, settings=CLOSED)
    ring(migrated_url, fake, carrier_id="leg-1")
    second = ring(migrated_url, fake, carrier_id="leg-2")
    assert len(call_backs(migrated_url)) == 1
    assert ("auto_callback_skipped", {"reason": "this caller was already called back today"}) in (
        events(migrated_url, second.call_id)
    )


def test_the_dialer_places_the_call_back_under_the_callback_rule(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, dialing = carrier
    inbound_employee(api, migrated_url, settings=CLOSED)
    ring(migrated_url, fake)
    assert tick(migrated_url, dialing, NOW) == []  # not due yet
    placed = tick(migrated_url, dialing, NOW + timedelta(minutes=2))
    assert len(placed) == 1 and len(fake.placed) == 1
    assert fake.placed[0]["to"] == CALLER.removeprefix("+") and fake.placed[0]["from"] in (
        NUMBER,
        NUMBER.removeprefix("+"),
    )
    (back,) = call_backs(migrated_url)
    assert back["status"] == "ringing"


def test_the_callback_rule_can_stop_it_where_the_instant_rule_would_allow_it(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, dialing = carrier
    inbound_employee(api, migrated_url, settings=CLOSED)
    sql(
        migrated_url,
        "UPDATE dial_rules SET allowed = false, reason = 'no call-backs here'"
        " WHERE context = 'callback'",
    )
    ring(migrated_url, fake)
    dialed = tick(migrated_url, dialing, NOW + timedelta(minutes=2))
    assert [d.outcome for d in dialed] == ["cancelled"]
    (back,) = call_backs(migrated_url)
    assert back["status"] == "canceled" and fake.placed == []
    assert any(
        t == "cancelled" and d["reason"] == "no call-backs here"
        for t, d in events(migrated_url, back["id"])
    )


def test_a_call_back_nobody_picks_up_is_not_tried_again_and_nor_is_a_missed_inbound_call(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, dialing = carrier
    inbound_employee(api, migrated_url, settings=CLOSED)
    ring(migrated_url, fake)
    tick(migrated_url, dialing, NOW + timedelta(minutes=2))

    async def ended_unanswered(factory: Any) -> list[Any]:
        async with factory() as session:
            back = await session.scalar(select(Call).where(Call.is_callback.is_(True)))
            assert back is not None
            first = await dialer.settle(
                session, back, CallStatus.NO_ANSWER, NOW + timedelta(minutes=3), 0
            )
            inbound = await session.scalar(select(Call).where(Call.callback_of_id.is_(None)))
            assert inbound is not None
            inbound.status = CallStatus.RINGING
            second = await dialer.settle(
                session, inbound, CallStatus.NO_ANSWER, NOW + timedelta(minutes=3), 0
            )
            await session.commit()
            return [first, second]

    assert run_db(migrated_url, ended_unanswered) == [None, None]
    assert sql(migrated_url, "SELECT count(*) FROM calls WHERE status = 'queued'") == 0


def test_a_call_back_an_inbound_employee_was_asked_for_is_dialed_like_any_other(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    """The caller asked, on a call, to be rung later: it was queued on the inbound channel."""
    fake, dialing = carrier
    inbound_employee(api, migrated_url)
    account = sql(migrated_url, "SELECT account_id FROM employees")
    employee = sql(migrated_url, "SELECT id FROM employees")
    lead = sql(
        migrated_url,
        "INSERT INTO leads (account_id, phone) VALUES (:a, :p) RETURNING id",
        {"a": account, "p": CALLER},
    )
    sql(
        migrated_url,
        "INSERT INTO calls (account_id, employee_id, lead_id, direction, channel, status,"
        " scheduled_for, attempt, is_callback) VALUES (:a, :e, :l, 'outbound', 'inbound', 'queued',"
        " :at, 1, true)",
        {"a": account, "e": employee, "l": lead, "at": NOW},
    )
    assert len(tick(migrated_url, dialing, NOW)) == 1 and len(fake.placed) == 1
