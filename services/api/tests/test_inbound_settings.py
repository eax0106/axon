"""Inbound settings and opening hours are plain functions of the settings and of the time."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.inbound.settings import InboundSettings, OpenWindow, is_open, of

WEEKDAYS = OpenWindow(days=[0, 1, 2, 3, 4], start_min=9 * 60, end_min=18 * 60)


def ist(day: int, hour: int, minute: int = 0) -> datetime:
    """A moment in India time: 2026-11-02 is a Monday, so `day` 0 is that Monday."""
    return datetime(2026, 11, 2 + day, hour, minute, tzinfo=timezone(timedelta(minutes=330)))


def test_the_defaults_answer_round_the_clock_and_take_a_message_when_shut() -> None:
    settings = of(None)
    assert settings.always_open and settings.closed_mode == "take_message"
    assert is_open(ist(5, 3), settings)  # 3 AM on a Saturday
    assert settings.auto_callback and settings.daily_summary and settings.answer_callbacks


def test_opening_windows_are_read_in_india_time_with_the_start_in_and_the_end_out() -> None:
    settings = InboundSettings(always_open=False, hours=[WEEKDAYS])
    assert not is_open(ist(0, 8, 59), settings)
    assert is_open(ist(0, 9), settings)
    assert is_open(ist(4, 17, 59), settings)
    assert not is_open(ist(4, 18), settings)  # the end is out
    assert not is_open(ist(5, 11), settings)  # Saturday
    # 03:30 UTC on Monday is 09:00 IST: the window is IST, not UTC.
    assert is_open(datetime(2026, 11, 2, 3, 30, tzinfo=UTC), settings)
    assert not is_open(datetime(2026, 11, 2, 3, 29, tzinfo=UTC), settings)


def test_several_windows_in_one_week() -> None:
    saturday = OpenWindow(days=[5], start_min=10 * 60, end_min=14 * 60)
    settings = InboundSettings(always_open=False, hours=[WEEKDAYS, saturday])
    assert is_open(ist(5, 12), settings) and not is_open(ist(5, 15), settings)
    assert not is_open(ist(6, 12), settings)  # Sunday


@pytest.mark.parametrize(
    "bad",
    [
        {"always_open": False},  # nothing says when it is open
        {"hours": [{"days": [7], "start_min": 0, "end_min": 60}]},
        {"hours": [{"days": [1, 1], "start_min": 0, "end_min": 60}]},
        {"hours": [{"days": [1], "start_min": 600, "end_min": 600}]},
        {"hours": [{"days": [1], "start_min": 1200, "end_min": 100}]},  # overnight: use two
        {"transfer_number": "12345"},
        {"transfer_number": "+14155550101"},  # not an Indian number
        {"transfer_number": "+919876543210"},  # no word on when to transfer
        {"closed_mode": "ignore"},
        {"greeting_new": "Hello {{name}}"},  # a new caller has no name yet
        {"greeting_returning": "Hello {{secret}}"},
        {"disclosure": "x" * 201},
    ],
)
def test_every_bad_value_is_refused(bad: dict[str, object]) -> None:
    body = {"always_open": True, **bad}
    with pytest.raises(ValidationError):
        InboundSettings.model_validate(body)


def test_a_transfer_number_is_stored_in_one_form_and_needs_a_condition() -> None:
    settings = InboundSettings(
        transfer_number="98765 43210",
        transfer_when="the caller asks for a person",
    )
    assert settings.transfer_number == "+919876543210"
    landline = InboundSettings(transfer_number="+91 40 2345 6789", transfer_when="angry caller")
    assert landline.transfer_number == "+914023456789"


def test_the_greetings_may_use_the_business_and_the_returning_one_the_name() -> None:
    InboundSettings(
        greeting_new="Welcome to {{business_name}}.",
        greeting_returning="Welcome back {{ name }}, this is {{business_name}}.",
        closed_message="{{business_name}} is closed.",
    )
