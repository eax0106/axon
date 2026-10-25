"""Dialer rules for the Instant channel, as pure functions of time.

Nothing here reads the clock or the database: every function takes `now`, so the tests can walk
a lead through a whole day. Times are timezone-aware datetimes. The functions take the UTC offset
as a parameter so tests can show it matters, but the dialer always passes `IST`: the hard limit is
measured in the callee's time, and every number we can dial is Indian (no daylight saving).

Hard limits, not settings: calls only between 6 AM and 10 PM local time (the default window is
9 AM to 9 PM; see DialerSettings). Start is inclusive and
end exclusive, so 21:59 may dial and 22:00 may not.
"""

from datetime import UTC, datetime, time, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

IST = 330  # minutes east of UTC. Every dialable number is Indian, so the calling hours are India's.
HARD_START_MIN, HARD_END_MIN = 6 * 60, 22 * 60
MAX_LADDER_STEPS = 9  # 1 first attempt + 9 retries = 10 attempts
OutOfWindow = Literal["next_window", "plus_3h", "plus_6h", "next_day", "hold"]


class DialerSettings(BaseModel):
    dial_delay_s: int = Field(default=0, ge=0, le=3600)
    # Default 9 AM to 9 PM, inside the hard 6 AM to 10 PM limit: TRAI's default-allowed band for
    # promotional calls is narrower than the hard limit, and the owner can widen it.
    window_start_min: int = Field(default=9 * 60, ge=HARD_START_MIN, le=HARD_END_MIN)
    window_end_min: int = Field(default=21 * 60, ge=HARD_START_MIN, le=HARD_END_MIN)
    days: list[int] = Field(default_factory=lambda: list(range(7)), min_length=1, max_length=7)
    out_of_window: OutOfWindow = "next_window"
    # Minutes to wait after each failed attempt. Up to 9 steps = 10 attempts in all.
    retry_ladder_min: list[int] = Field(default_factory=lambda: [10, 60, 180, 1440], max_length=9)
    dedup_recent_days: int = Field(default=1, ge=0, le=90)

    @field_validator("days")
    @classmethod
    def _days(cls, days: list[int]) -> list[int]:
        if any(d < 0 or d > 6 for d in days) or len(set(days)) != len(days):
            raise ValueError("days are distinct weekday numbers 0 (Monday) to 6 (Sunday)")
        return sorted(days)

    @field_validator("retry_ladder_min")
    @classmethod
    def _ladder(cls, steps: list[int]) -> list[int]:
        if any(s < 1 or s > 10080 for s in steps):
            raise ValueError("each retry wait is 1 minute to 7 days")
        return steps

    @model_validator(mode="after")
    def _window(self) -> "DialerSettings":
        if self.window_end_min <= self.window_start_min:
            raise ValueError("the calling window must end after it starts")
        return self

    @property
    def max_attempts(self) -> int:
        return 1 + len(self.retry_ladder_min)


def local(now: datetime, offset_min: int) -> datetime:
    return now.astimezone(timezone(timedelta(minutes=offset_min)))


def in_window(at: datetime, settings: DialerSettings, offset_min: int) -> bool:
    here = local(at, offset_min)
    minute = here.hour * 60 + here.minute
    return (
        here.weekday() in settings.days
        and settings.window_start_min <= minute < settings.window_end_min
    )


def next_window_start(at: datetime, settings: DialerSettings, offset_min: int) -> datetime:
    """The first moment on or after `at` that is inside the calling window."""
    if in_window(at, settings, offset_min):
        return at
    here = local(at, offset_min)
    start = time(settings.window_start_min // 60, settings.window_start_min % 60)
    for ahead in range(0, 9):
        day = here.date() + timedelta(days=ahead)
        candidate = datetime.combine(day, start, tzinfo=here.tzinfo)
        if candidate >= here and candidate.weekday() in settings.days:
            return candidate.astimezone(UTC)
    raise AssertionError("days has at least one weekday, so a window starts within a week")


def adjust(at: datetime, settings: DialerSettings, offset_min: int) -> datetime | None:
    """`at` if it is inside the window, else when the out-of-window rule says to try; None = hold
    (do not dial until someone redials)."""
    if in_window(at, settings, offset_min):
        return at
    rule = settings.out_of_window
    if rule == "hold":
        return None
    if rule == "next_window":
        return next_window_start(at, settings, offset_min)
    if rule == "next_day":
        tomorrow = local(at, offset_min).date() + timedelta(days=1)
        midnight = datetime.combine(tomorrow, time(0), tzinfo=local(at, offset_min).tzinfo)
        return next_window_start(midnight.astimezone(UTC), settings, offset_min)
    later = at + timedelta(hours=3 if rule == "plus_3h" else 6)
    return next_window_start(later, settings, offset_min)


def first_attempt_time(now: datetime, settings: DialerSettings, offset_min: int) -> datetime | None:
    return adjust(now + timedelta(seconds=settings.dial_delay_s), settings, offset_min)


def has_retry(failed_attempt: int, settings: DialerSettings) -> bool:
    return 1 <= failed_attempt <= len(settings.retry_ladder_min)


def retry_time(
    failed_attempt: int, now: datetime, settings: DialerSettings, offset_min: int
) -> datetime | None:
    """When to make attempt `failed_attempt + 1` (only call this when `has_retry`); None = the
    out-of-window rule is hold, so the retry waits for a redial."""
    wait = timedelta(minutes=settings.retry_ladder_min[failed_attempt - 1])
    return adjust(now + wait, settings, offset_min)
