from datetime import datetime
from typing import Any

from fastapi.testclient import TestClient

from app.actions.booking import IST, free_slots
from app.actions.schema import CalendarBooking
from app.providers.base import Busy

from .actions_support import Google, calendar_action, connect_google, use
from .helpers import signup

MONDAY_9AM = datetime(2026, 11, 2, 9, 0, tzinfo=IST)
CALL = "2fe5e0a4-7d8c-4a1f-9c1b-3a1f4f0c9d11"


def cfg(**changes: Any) -> CalendarBooking:
    return CalendarBooking.model_validate(calendar_action(**changes))


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=IST)


def times(slots: list[datetime]) -> list[str]:
    return [f"{s:%H:%M}" for s in slots]


def test_free_times_are_working_hours_in_steps_of_one_appointment() -> None:
    slots = free_slots(cfg(), at(2, 0).date(), MONDAY_9AM, [])
    assert times(slots)[0] == "10:00" and times(slots)[-1] == "17:30" and len(slots) == 16
    odd = free_slots(cfg(duration_min=45), at(2, 0).date(), MONDAY_9AM, [])
    assert times(odd)[-1] == "16:45"  # 17:30 would run to 18:15


def test_nothing_is_offered_on_closed_days_in_the_past_or_beyond_the_window() -> None:
    sunday, saturday = at(8, 0).date(), at(7, 0).date()
    assert free_slots(cfg(), sunday, MONDAY_9AM, []) == []
    assert free_slots(cfg(), saturday, MONDAY_9AM, []) != []
    assert free_slots(cfg(), at(1, 0).date(), MONDAY_9AM, []) == []
    assert free_slots(cfg(days_ahead=3), at(6, 0).date(), MONDAY_9AM, []) == []
    assert free_slots(cfg(days_ahead=3), at(5, 0).date(), MONDAY_9AM, []) != []


def test_the_minimum_notice_moves_the_first_free_time_later() -> None:
    now = at(2, 10, 15)
    assert times(free_slots(cfg(), at(2, 0).date(), now, []))[0] == "11:30"
    assert times(free_slots(cfg(min_notice_min=0), at(2, 0).date(), now, []))[0] == "10:30"


def test_a_busy_time_removes_every_slot_it_touches_and_only_those() -> None:
    busy = [Busy(at(2, 10, 45), at(2, 11, 15))]
    assert "10:30" not in times(free_slots(cfg(), at(2, 0).date(), MONDAY_9AM, busy))
    assert "11:00" not in times(free_slots(cfg(), at(2, 0).date(), MONDAY_9AM, busy))
    assert "11:30" in times(free_slots(cfg(), at(2, 0).date(), MONDAY_9AM, busy))
    touching = [Busy(at(2, 11, 0), at(2, 11, 30))]
    kept = times(free_slots(cfg(), at(2, 0).date(), MONDAY_9AM, touching))
    assert "10:30" in kept and "11:30" in kept and "11:00" not in kept


def connected(
    actions_api: tuple[TestClient, Google],
) -> tuple[TestClient, Google, dict[str, str]]:
    client, google = actions_api
    owner = signup(client)
    connect_google(client, owner)
    return client, google, owner


def run(
    url: str,
    client: TestClient,
    owner: dict[str, str],
    calls: list[tuple[str, dict[str, Any]]],
    **changes: Any,
) -> list[dict[str, Any]]:
    return use(
        url, client, owner, [calendar_action(**changes)], calls,
        call_id=CALL, party_phone="+919876543210", now=lambda: MONDAY_9AM,
    )  # fmt: skip


def test_the_free_times_tool_names_the_day_and_lists_only_free_times(
    actions_api: tuple[TestClient, Google], migrated_url: str
) -> None:
    client, google, owner = connected(actions_api)
    google.busy = [("2026-11-03T10:00:00+05:30", "2026-11-03T11:00:00+05:30")]
    [free] = run(migrated_url, client, owner, [("visit_availability", {"date": "2026-11-03"})])
    assert free["ok"] and free["weekday"] == "Tuesday"
    assert free["free_times"][:2] == ["11:00", "11:30"]
    [bad] = run(migrated_url, client, owner, [("visit_availability", {"date": "tomorrow"})])
    assert bad == {"ok": False, "error": "date must be written YYYY-MM-DD"}


def test_booking_puts_one_event_on_the_calendar_and_invites_nobody(
    actions_api: tuple[TestClient, Google], migrated_url: str
) -> None:
    client, google, owner = connected(actions_api)
    [done] = run(
        migrated_url, client, owner,
        [("visit_book", {"start": "2026-11-03 11:30", "name": "Asha\nRao"})],
        title="Site visit", duration_min=45,
    )  # fmt: skip
    assert done == {"ok": True, "booked": "Tuesday 3 November 2026, 11:30 AM"}
    [event] = google.events.values()
    assert event["summary"] == "Site visit" and "attendees" not in event
    assert event["start"]["dateTime"] == "2026-11-03T11:30:00+05:30"
    assert event["end"]["dateTime"] == "2026-11-03T12:15:00+05:30"
    assert "Name: Asha Rao" in event["description"] and "+919876543210" in event["description"]


def test_the_same_booking_made_twice_on_one_call_is_one_event(
    actions_api: tuple[TestClient, Google], migrated_url: str
) -> None:
    client, google, owner = connected(actions_api)
    args = {"start": "2026-11-03 11:30", "name": "Asha"}
    calls = [("visit_book", args), ("visit_book", args)]
    first, second = run(migrated_url, client, owner, calls)
    assert first["ok"] and "already" not in first
    assert second["ok"] and second["already"] is True and len(google.events) == 1


def test_a_time_that_was_free_but_is_taken_by_the_time_of_booking_is_refused(
    actions_api: tuple[TestClient, Google], migrated_url: str
) -> None:
    client, google, owner = connected(actions_api)
    google.busy = [("2026-11-03T11:30:00+05:30", "2026-11-03T12:00:00+05:30")]
    [late] = run(
        migrated_url, client, owner, [("visit_book", {"start": "2026-11-03 11:30", "name": "A"})]
    )
    assert late["ok"] is False and "not free" in late["error"] and google.events == {}


def test_a_time_outside_the_offer_is_never_booked(
    actions_api: tuple[TestClient, Google], migrated_url: str
) -> None:
    client, google, owner = connected(actions_api)
    for start in (
        "2026-11-03 07:00",  # before opening
        "2026-11-03 10:15",  # between slots
        "2026-11-08 11:00",  # a Sunday
        "2026-11-02 08:00",  # already past
        "2026-12-30 11:00",  # beyond the window
        "2026-11-03 17:45",  # would run past closing
    ):
        [result] = run(migrated_url, client, owner, [("visit_book", {"start": start, "name": "A"})])
        assert result["ok"] is False, start
    assert google.events == {}


def test_a_late_slot_of_a_long_day_can_be_booked(
    actions_api: tuple[TestClient, Google], migrated_url: str
) -> None:
    client, _google, owner = connected(actions_api)
    [result] = run(
        migrated_url, client, owner, [("visit_book", {"start": "2026-11-03 17:30", "name": "A"})]
    )
    assert result["ok"] is True  # more than the dozen times that are read out to the AI


def test_booking_needs_a_name_a_readable_time_and_a_connected_calendar(
    actions_api: tuple[TestClient, Google], migrated_url: str
) -> None:
    client, _google, owner = connected(actions_api)
    [no_name, bad_time] = run(
        migrated_url,
        client,
        owner,
        [
            ("visit_book", {"start": "2026-11-03 11:00"}),
            ("visit_book", {"start": "soon", "name": "A"}),
        ],
    )
    assert "name is needed" in no_name["error"] and "YYYY-MM-DD HH:MM" in bad_time["error"]
    other = signup(client, "other@example.com", "Other")  # never connected Google
    [unconnected] = run(
        migrated_url, client, other, [("visit_availability", {"date": "2026-11-03"})]
    )
    assert unconnected == {"ok": False, "error": "the calendar is not connected"}


def test_a_calendar_google_cannot_read_is_a_failure_not_an_empty_day(
    actions_api: tuple[TestClient, Google], migrated_url: str
) -> None:
    client, google, owner = connected(actions_api)
    google.calendar_error = "notFound"
    [result] = run(migrated_url, client, owner, [("visit_availability", {"date": "2026-11-03"})])
    assert result == {"ok": False, "error": "that is not available right now"}
