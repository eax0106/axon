"""Dialer rules walked through simulated time. IST = UTC+5:30, so 06:00 IST is 00:30 UTC."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from app.instant import rules
from app.instant.rules import DialerSettings

IST = 330
FULL = DialerSettings(window_start_min=6 * 60, window_end_min=22 * 60)  # the hard limits


def utc(y: int, mo: int, d: int, h: int, mi: int = 0, s: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, s, tzinfo=UTC)


def ist(y: int, mo: int, d: int, h: int, mi: int = 0, s: int = 0) -> datetime:
    return utc(y, mo, d, h, mi, s) - timedelta(minutes=IST)


MON = (2026, 11, 2)  # a Monday
SAT = (2026, 11, 7)


@pytest.mark.parametrize(
    ("at", "inside"),
    [
        (ist(*MON, 5, 59, 59), False),
        (ist(*MON, 6, 0), True),  # start is inclusive
        (ist(*MON, 12, 0), True),
        (ist(*MON, 21, 59, 59), True),
        (ist(*MON, 22, 0), False),  # end is exclusive
        (ist(*MON, 23, 30), False),
        (ist(*MON, 3, 0), False),
    ],
)
def test_the_widest_window_is_6am_to_10pm_to_the_second(at: datetime, inside: bool) -> None:
    assert rules.in_window(at, FULL, IST) is inside


def test_the_default_window_is_9am_to_9pm() -> None:
    default = DialerSettings()
    assert not rules.in_window(ist(*MON, 8, 59), default, IST)
    assert rules.in_window(ist(*MON, 9, 0), default, IST)
    assert rules.in_window(ist(*MON, 20, 59), default, IST)
    assert not rules.in_window(ist(*MON, 21, 0), default, IST)


def test_the_window_follows_the_accounts_utc_offset() -> None:
    noon_utc = utc(*MON, 12, 0)  # 17:30 IST, 07:00 at -05:00, 12:00 at UTC
    settings = FULL
    assert rules.in_window(noon_utc, settings, IST)
    assert rules.in_window(noon_utc, settings, -300)
    assert rules.in_window(utc(*MON, 4, 0), settings, 0) is False  # 04:00 UTC
    assert rules.in_window(utc(*MON, 4, 0), settings, IST)  # 09:30 IST
    assert rules.in_window(utc(*MON, 4, 0), settings, -300) is False  # 23:00 the day before


def test_a_narrower_window_and_weekdays_are_respected() -> None:
    settings = DialerSettings(window_start_min=9 * 60, window_end_min=18 * 60, days=[0, 1, 2, 3, 4])
    assert rules.in_window(ist(*MON, 9, 0), settings, IST)
    assert not rules.in_window(ist(*MON, 8, 59), settings, IST)
    assert not rules.in_window(ist(*MON, 18, 0), settings, IST)
    assert not rules.in_window(ist(*SAT, 12, 0), settings, IST)


def test_the_six_to_ten_limit_cannot_be_widened() -> None:
    bad_windows: list[dict[str, int]] = [
        {"window_start_min": 5 * 60 + 59},
        {"window_end_min": 22 * 60 + 1},
    ]
    for bad in bad_windows:
        with pytest.raises(ValidationError):
            DialerSettings.model_validate(bad)
    with pytest.raises(ValidationError):
        DialerSettings(window_start_min=600, window_end_min=600)


def test_settings_validation() -> None:
    bad_settings: list[dict[str, Any]] = [
        {"days": []},
        {"days": [7]},
        {"days": [1, 1]},
        {"retry_ladder_min": [0]},
        {"retry_ladder_min": [5] * 10},
        {"dial_delay_s": -1},
        {"dedup_recent_days": 91},
        {"out_of_window": "whenever"},
    ]
    for bad in bad_settings:
        with pytest.raises(ValidationError):
            DialerSettings.model_validate(bad)
    assert DialerSettings(retry_ladder_min=[5] * 9).max_attempts == 10


def test_inside_the_window_nothing_moves() -> None:
    at = ist(*MON, 10, 15)
    assert rules.adjust(at, FULL, IST) == at


def test_next_window_waits_for_the_next_opening() -> None:
    settings = FULL.model_copy(update={"out_of_window": "next_window"})
    late = ist(*MON, 22, 30)
    assert rules.adjust(late, settings, IST) == ist(2026, 11, 3, 6, 0)
    early = ist(*MON, 4, 0)
    assert rules.adjust(early, settings, IST) == ist(*MON, 6, 0)


def test_next_window_skips_days_that_are_not_allowed() -> None:
    weekdays = FULL.model_copy(update={"days": [0, 1, 2, 3, 4]})
    friday_night = ist(2026, 11, 6, 22, 30)
    assert rules.adjust(friday_night, weekdays, IST) == ist(2026, 11, 9, 6, 0)  # Monday
    assert rules.adjust(ist(*SAT, 10, 0), weekdays, IST) == ist(2026, 11, 9, 6, 0)


@pytest.mark.parametrize(
    ("rule", "at", "expected"),
    [
        ("plus_3h", ist(*MON, 5, 0), ist(*MON, 8, 0)),  # +3h lands inside the window
        ("plus_3h", ist(*MON, 22, 30), ist(2026, 11, 3, 6, 0)),  # +3h is 01:30: next window
        ("plus_6h", ist(*MON, 4, 0), ist(*MON, 10, 0)),
        ("plus_6h", ist(*MON, 23, 0), ist(2026, 11, 3, 6, 0)),  # 05:00 next day is still shut
        ("next_day", ist(*MON, 22, 30), ist(2026, 11, 3, 6, 0)),
        ("next_day", ist(*MON, 4, 0), ist(2026, 11, 3, 6, 0)),  # tomorrow, not later today
    ],
)
def test_each_out_of_window_rule(rule: str, at: datetime, expected: datetime) -> None:
    settings = FULL.model_copy(update={"out_of_window": rule})
    assert rules.adjust(at, settings, IST) == expected


def test_hold_means_no_automatic_call() -> None:
    assert rules.adjust(ist(*MON, 23, 0), DialerSettings(out_of_window="hold"), IST) is None
    assert rules.adjust(ist(*MON, 9, 0), DialerSettings(out_of_window="hold"), IST) == ist(
        *MON, 9, 0
    )


def test_first_attempt_waits_the_dial_delay_then_the_window() -> None:
    settings = FULL.model_copy(update={"dial_delay_s": 90})
    assert rules.first_attempt_time(ist(*MON, 10, 0), settings, IST) == ist(*MON, 10, 1, 30)
    # A lead arriving 21:59:30 with a 90 s delay would dial at 22:01: moved to the next window.
    assert rules.first_attempt_time(ist(*MON, 21, 59, 30), settings, IST) == ist(2026, 11, 3, 6, 0)
    assert rules.first_attempt_time(ist(*MON, 21, 59, 30), FULL, IST) == ist(*MON, 21, 59, 30)


def test_the_retry_ladder_gives_up_to_ten_attempts() -> None:
    ladder = [5, 10, 15, 20, 25, 30, 35, 40, 45]
    settings = DialerSettings(retry_ladder_min=ladder)
    assert settings.max_attempts == 10
    now = ist(*MON, 10, 0)
    for failed in range(1, 10):
        assert rules.has_retry(failed, settings)
        assert rules.retry_time(failed, now, settings, IST) == now + timedelta(
            minutes=ladder[failed - 1]
        )
    assert not rules.has_retry(10, settings)  # the 10th attempt is the last
    assert not rules.has_retry(0, settings)
    assert not rules.has_retry(1, DialerSettings(retry_ladder_min=[]))


def test_a_retry_that_lands_outside_the_window_follows_the_rule() -> None:
    settings = FULL.model_copy(update={"retry_ladder_min": [60]})
    assert rules.retry_time(1, ist(*MON, 21, 30), settings, IST) == ist(2026, 11, 3, 6, 0)
    held = FULL.model_copy(update={"retry_ladder_min": [60], "out_of_window": "hold"})
    assert rules.retry_time(1, ist(*MON, 21, 30), held, IST) is None
    assert rules.has_retry(1, held)  # held is not the same as used up


def test_whole_day_walk_each_minute_obeys_the_window() -> None:
    settings = FULL
    start = ist(*MON, 0, 0)
    opened = [
        m for m in range(24 * 60) if rules.in_window(start + timedelta(minutes=m), settings, IST)
    ]
    assert (opened[0], opened[-1], len(opened)) == (6 * 60, 22 * 60 - 1, 16 * 60)
