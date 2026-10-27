"""A call arrives on a number: answered or missed, and recorded either way."""

import pytest
from fastapi.testclient import TestClient

from .conftest import sql
from .dialing import Carrier
from .inbound_support import NOW, NUMBER, calls, events, inbound_employee, ring


def test_a_live_employee_answers_and_the_call_is_recorded(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    employee, _owner = inbound_employee(api, migrated_url)
    routed = ring(migrated_url, fake, carrier_id="leg-1")
    assert routed.kind == "answer" and str(routed.employee_id) == employee
    assert routed.language == "en" and not routed.closed
    (call,) = calls(migrated_url)
    assert call["direction"] == "inbound" and call["status"] == "ringing"
    assert call["carrier_call_id"] == call["carrier_leg_id"] == "leg-1"
    assert call["caller_phone"] == "+919876543210" and call["miss_reason"] is None
    lead = sql(migrated_url, "SELECT phone FROM leads")
    assert lead == "+919876543210" and call["lead_id"] is not None
    assert events(migrated_url, call["id"])[0] == (
        "inbound_routed",
        {"closed": False, "returning": False},
    )


def test_the_same_carrier_call_asked_twice_is_one_call(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    inbound_employee(api, migrated_url)
    first = ring(migrated_url, fake, carrier_id="leg-1")
    second = ring(migrated_url, fake, carrier_id="leg-1")
    assert first.call_id == second.call_id and second.kind == "answer"
    assert len(calls(migrated_url)) == 1


def test_a_known_caller_is_a_returning_caller_and_one_lead_not_two(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    inbound_employee(api, migrated_url)
    ring(migrated_url, fake, carrier_id="leg-1")
    sql(migrated_url, "UPDATE calls SET status = 'completed', ended_at = now()")
    ring(migrated_url, fake, carrier_id="leg-2")
    assert sql(migrated_url, "SELECT count(*) FROM leads") == 1
    second = calls(migrated_url)[1]
    assert events(migrated_url, second["id"])[0][1]["returning"] is True


def test_a_call_the_carrier_does_not_have_is_not_believed(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    inbound_employee(api, migrated_url)
    assert ring(migrated_url, fake, carrier_id="forged", live=False).kind == "unknown"
    assert calls(migrated_url) == []  # nothing recorded, no channel held


def test_a_number_that_is_not_ours_is_unknown_and_leaves_no_trace(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    inbound_employee(api, migrated_url)
    assert ring(migrated_url, fake, to="+919100000099").kind == "unknown"
    assert calls(migrated_url) == []


RULE_SAYS_NO = (
    "UPDATE dial_rules SET allowed = false, reason = 'a rule says no' WHERE context = 'inbound'"
)
REFUSALS = [
    ("paused", "UPDATE employees SET status = 'paused'", "paused"),
    ("credits", "UPDATE accounts SET credit_balance = 0", "no credits"),
    ("rule", RULE_SAYS_NO, "a rule says no"),
    ("unattached", "UPDATE employees SET number_id = NULL", "no AI employee"),
]


@pytest.mark.parametrize(("code", "change", "words"), REFUSALS)
def test_a_call_is_missed_with_a_plain_reason(
    api: TestClient,
    migrated_url: str,
    carrier: tuple[Carrier, None],
    code: str,
    change: str,
    words: str,
) -> None:
    fake, _ = carrier
    inbound_employee(api, migrated_url)
    sql(migrated_url, change)
    routed = ring(migrated_url, fake, carrier_id="leg-1")
    assert routed.kind == "missed" and routed.code == code
    assert routed.reason is not None and words in routed.reason
    (call,) = calls(migrated_url)
    assert call["status"] == "no_answer" and call["miss_reason"] == routed.reason
    assert call["billing_status"] == "free" and call["ended_at"] is not None
    assert events(migrated_url, call["id"])[0][0] == "missed"


def test_an_outbound_employee_that_does_not_take_callbacks_misses_the_call(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    _, _owner = inbound_employee(
        api, migrated_url, channel="instant", settings={"answer_callbacks": False}
    )
    routed = ring(migrated_url, fake)
    assert routed.kind == "missed" and routed.code == "no_callbacks"
    assert routed.reason is not None and "only makes calls" in routed.reason


def test_closed_hours_either_take_a_message_or_do_not_answer(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    hours = {
        "always_open": False,
        "hours": [{"days": [1], "start_min": 600, "end_min": 700}],  # Tuesdays only
    }
    employee, owner = inbound_employee(api, migrated_url, settings=hours)
    closed = ring(migrated_url, fake, carrier_id="leg-1", now=NOW)  # Monday
    assert closed.kind == "answer" and closed.closed
    sql(migrated_url, "UPDATE calls SET status = 'completed', ended_at = now()")
    api.put(
        f"/employees/{employee}/inbound-settings",
        json={**hours, "closed_mode": "hang_up"},
        headers=owner,
    )
    shut = ring(migrated_url, fake, carrier_id="leg-2", now=NOW)
    assert shut.kind == "missed" and shut.code == "closed"
    assert shut.reason is not None and "opening hours" in shut.reason


def test_the_account_hears_when_callers_are_turned_away_for_credits_but_not_every_time(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    inbound_employee(api, migrated_url)
    sql(migrated_url, "UPDATE accounts SET credit_balance = 0")
    for n in range(3):
        ring(migrated_url, fake, carrier_id=f"leg-{n}", caller=f"+91987654321{n}")
    assert (
        sql(
            migrated_url, "SELECT count(*) FROM notifications WHERE kind = 'inbound_missed_credits'"
        )
        == 1
    )


def test_a_call_from_a_withheld_number_is_still_answered_without_a_lead(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    inbound_employee(api, migrated_url)
    assert ring(migrated_url, fake, caller="anonymous").kind == "answer"
    (call,) = calls(migrated_url)
    assert call["lead_id"] is None and call["caller_phone"] is None
    assert NUMBER  # the number itself is unchanged
