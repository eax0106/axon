"""A campaign's settings and calling hours, as pure functions of simulated time (fixed IST)."""

from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.campaigns import settings as schedule
from app.campaigns.settings import CampaignSettings

MONDAY_11 = datetime(2026, 11, 2, 5, 30, tzinfo=UTC)  # 11:00 IST, a Monday


def ist(day: int, hour: int, minute: int = 0) -> datetime:
    """A November 2026 moment given in IST."""
    return datetime(2026, 11, day, hour, minute, tzinfo=UTC) - timedelta(hours=5, minutes=30)


def test_the_defaults_are_the_nine_to_nine_window_two_lines_and_two_retries() -> None:
    s = CampaignSettings()
    assert (s.window_start_min, s.window_end_min) == (9 * 60, 21 * 60)
    assert s.days == [0, 1, 2, 3, 4, 5, 6] and s.holidays == []
    assert (s.concurrency, s.retries, s.skip_dnc, s.dedupe_days, s.repeat) == (
        2,
        2,
        True,
        7,
        "none",
    )
    assert s.max_attempts == 3


@pytest.mark.parametrize(
    "bad",
    [
        {"window_start_min": 8 * 60 + 59},  # earlier than 9 AM: a hard limit for cold calls
        {"window_end_min": 21 * 60 + 1},  # later than 9 PM
        {"window_start_min": 15 * 60, "window_end_min": 15 * 60},
        {"concurrency": 0},
        {"concurrency": 21},
        {"retries": 10},
        {"retries": -1},
        {"days": []},
        {"days": [0, 0]},
        {"days": [7]},
        {"retry_gap_min": 0},
        {"dedupe_days": 91},
        {"repeat": "monthly"},
        {"retry_mode": "whenever"},
    ],
)
def test_settings_outside_the_limits_are_refused(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CampaignSettings(**bad)  # type: ignore[arg-type]


def test_the_limits_themselves_are_allowed() -> None:
    s = CampaignSettings(concurrency=20, retries=9, window_start_min=540, window_end_min=1260)
    assert s.max_attempts == 10


def test_holidays_are_sorted_and_deduplicated() -> None:
    s = CampaignSettings(holidays=[date(2026, 11, 9), date(2026, 11, 5), date(2026, 11, 9)])
    assert s.holidays == [date(2026, 11, 5), date(2026, 11, 9)]


def test_the_window_start_is_inclusive_and_the_end_exclusive() -> None:
    s = CampaignSettings()
    assert not schedule.in_window(ist(2, 8, 59), s)
    assert schedule.in_window(ist(2, 9), s)
    assert schedule.in_window(ist(2, 20, 59), s)
    assert not schedule.in_window(ist(2, 21), s)


def test_hours_are_measured_in_ist_not_utc() -> None:
    s = CampaignSettings()
    assert schedule.in_window(datetime(2026, 11, 2, 3, 30, tzinfo=UTC), s)  # 09:00 IST
    assert not schedule.in_window(datetime(2026, 11, 2, 3, 29, tzinfo=UTC), s)  # 08:59 IST


def test_days_and_holidays_close_the_window() -> None:
    s = CampaignSettings(days=[0, 1, 2, 3, 4], holidays=[date(2026, 11, 4)])
    assert schedule.in_window(ist(2, 12), s)  # Monday
    assert not schedule.in_window(ist(4, 12), s)  # a holiday
    assert not schedule.in_window(ist(7, 12), s)  # Saturday
    assert not schedule.in_window(ist(8, 12), s)  # Sunday


def test_next_open_is_now_inside_the_window_and_the_next_opening_otherwise() -> None:
    s = CampaignSettings(days=[0, 1, 2, 3, 4], holidays=[date(2026, 11, 9)])
    assert schedule.next_open(ist(2, 12), s) == ist(2, 12)
    assert schedule.next_open(ist(2, 21, 30), s) == ist(3, 9)  # tomorrow morning
    assert schedule.next_open(ist(2, 7), s) == ist(2, 9)  # earlier today
    assert schedule.next_open(ist(6, 12), s) == ist(6, 12)  # Friday noon is open
    # Monday 9 November is a holiday: from Friday evening the week-end and the holiday are skipped.
    assert schedule.next_open(ist(6, 22), s) == ist(10, 9)


def test_a_retry_in_the_same_run_waits_the_gap_and_never_into_the_night() -> None:
    s = CampaignSettings(retry_gap_min=60)
    assert schedule.retry_time(ist(2, 11), s) == ist(2, 12)
    assert schedule.retry_time(ist(2, 20, 30), s) == ist(3, 9)  # the gap ends after 9 PM


def test_a_retry_the_next_day_waits_for_the_window_of_a_later_day() -> None:
    s = CampaignSettings(retry_mode="next_day", holidays=[date(2026, 11, 3)])
    assert schedule.retry_time(ist(2, 11), s) == ist(4, 9)  # tomorrow is a holiday
    assert schedule.retry_time(ist(2, 23, 0), CampaignSettings(retry_mode="next_day")) == ist(3, 9)


def test_a_repeating_campaign_runs_again_at_the_same_time_a_day_or_week_on() -> None:
    assert schedule.next_run(ist(2, 10), CampaignSettings()) is None
    assert schedule.next_run(ist(2, 10), CampaignSettings(repeat="daily")) == ist(3, 10)
    assert schedule.next_run(ist(2, 10), CampaignSettings(repeat="weekly")) == ist(9, 10)
    shut = CampaignSettings(repeat="daily", days=[0, 1, 2, 3, 4])
    assert schedule.next_run(ist(6, 10), shut) == ist(9, 9)  # Friday -> Saturday is closed
    late = CampaignSettings(repeat="daily", window_end_min=11 * 60)
    assert schedule.next_run(ist(2, 10, 59), late) == ist(3, 10, 59)  # still inside the window
    assert schedule.next_run(ist(2, 11, 30), late) == ist(4, 9)  # 11:30 tomorrow is shut
