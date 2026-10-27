"""A campaign's settings, and the calling hours they imply, as pure functions of time.

Nothing here reads the clock or the database: every function takes `now`, so the tests can walk a
campaign through a week. Hours are fixed IST (DECISIONS, 2026-10-25). Bulk calls are cold calls, so
the window is held to 9 AM to 9 PM, narrower than the 6 AM to 10 PM limit of an Instant call.
"""

from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.instant import rules

HARD_START_MIN, HARD_END_MIN = 9 * 60, 21 * 60
MAX_RETRIES = 9  # 1 first attempt + 9 retries = 10 attempts
MAX_HOLIDAYS = 100
Repeat = Literal["none", "daily", "weekly"]
RetryMode = Literal["same_run", "next_day"]


class CampaignSettings(BaseModel):
    window_start_min: int = Field(default=HARD_START_MIN, ge=HARD_START_MIN, le=HARD_END_MIN)
    window_end_min: int = Field(default=HARD_END_MIN, ge=HARD_START_MIN, le=HARD_END_MIN)
    days: list[int] = Field(default_factory=lambda: list(range(7)), min_length=1, max_length=7)
    holidays: list[date] = Field(default_factory=list, max_length=MAX_HOLIDAYS)
    concurrency: int = Field(default=2, ge=1, le=20)
    skip_dnc: bool = True
    retries: int = Field(default=2, ge=0, le=MAX_RETRIES)
    # same_run: try again after `retry_gap_min` minutes, within the day's window; next_day: try
    # again when the window next opens on a later day.
    retry_mode: RetryMode = "same_run"
    retry_gap_min: int = Field(default=60, ge=1, le=1440)
    # Do not call a number another campaign of the account called in the last N days (0 = off).
    dedupe_days: int = Field(default=7, ge=0, le=90)
    repeat: Repeat = "none"

    @field_validator("days")
    @classmethod
    def _days(cls, days: list[int]) -> list[int]:
        if any(d < 0 or d > 6 for d in days) or len(set(days)) != len(days):
            raise ValueError("days are distinct weekday numbers 0 (Monday) to 6 (Sunday)")
        return sorted(days)

    @field_validator("holidays")
    @classmethod
    def _holidays(cls, holidays: list[date]) -> list[date]:
        return sorted(set(holidays))

    @model_validator(mode="after")
    def _window(self) -> "CampaignSettings":
        if self.window_end_min <= self.window_start_min:
            raise ValueError("the calling window must end after it starts")
        return self

    @property
    def max_attempts(self) -> int:
        return 1 + self.retries


def of(raw: dict[str, object] | None) -> CampaignSettings:
    return CampaignSettings.model_validate(raw or {})


def _open(day: date, settings: CampaignSettings) -> bool:
    return day.weekday() in settings.days and day not in settings.holidays


def in_window(at: datetime, settings: CampaignSettings) -> bool:
    here = rules.local(at, rules.IST)
    minute = here.hour * 60 + here.minute
    return _open(here.date(), settings) and (
        settings.window_start_min <= minute < settings.window_end_min
    )


def next_open(at: datetime, settings: CampaignSettings) -> datetime:
    """The first moment on or after `at` that is inside the calling window."""
    if in_window(at, settings):
        return at
    here = rules.local(at, rules.IST)
    start = time(settings.window_start_min // 60, settings.window_start_min % 60)
    for ahead in range(MAX_HOLIDAYS * 7 + 8):  # a free weekday exists within that many days
        day = here.date() + timedelta(days=ahead)
        candidate = datetime.combine(day, start, tzinfo=here.tzinfo)
        if candidate >= here and _open(day, settings):
            return candidate.astimezone(UTC)
    raise AssertionError("days has a weekday and holidays are bounded, so a window opens")


def window_minutes(settings: CampaignSettings) -> int:
    return settings.window_end_min - settings.window_start_min


def retry_time(now: datetime, settings: CampaignSettings) -> datetime:
    """When an unanswered contact may be tried again."""
    if settings.retry_mode == "next_day":
        tomorrow = rules.local(now, rules.IST).date() + timedelta(days=1)
        midnight = datetime.combine(tomorrow, time(0), tzinfo=rules.local(now, rules.IST).tzinfo)
        return next_open(midnight.astimezone(UTC), settings)
    return next_open(now + timedelta(minutes=settings.retry_gap_min), settings)


def next_run(after: datetime, settings: CampaignSettings) -> datetime | None:
    """When a repeating campaign next starts: the same time tomorrow or a week on, moved into the
    window if it falls outside it. None if the campaign does not repeat."""
    if settings.repeat == "none":
        return None
    step = timedelta(days=1 if settings.repeat == "daily" else 7)
    return next_open(after + step, settings)
