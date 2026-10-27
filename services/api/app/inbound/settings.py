"""An employee's settings for incoming calls: opening hours, greetings, transfer, auto call-back.

They live in `employees.inbound` (JSON) and, like voice settings, apply to the next call at once,
with no publish. The opening hours are India time (DECISIONS: calling hours are always fixed IST).
"""

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.instant.rules import IST, local

PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
NAME_PLACEHOLDERS = {"name", "business_name"}
# +91 and ten digits: a mobile or a landline with its area code. Separators are ignored.
INDIA_NUMBER = re.compile(r"^(?:\+?91)?([1-9]\d{9})$")


class OpenWindow(BaseModel):
    days: list[int] = Field(min_length=1, max_length=7)
    start_min: int = Field(ge=0, le=24 * 60 - 1)
    end_min: int = Field(ge=1, le=24 * 60)

    @field_validator("days")
    @classmethod
    def _days(cls, days: list[int]) -> list[int]:
        if any(d < 0 or d > 6 for d in days) or len(set(days)) != len(days):
            raise ValueError("days are distinct weekday numbers 0 (Monday) to 6 (Sunday)")
        return sorted(days)

    @model_validator(mode="after")
    def _order(self) -> "OpenWindow":
        if self.end_min <= self.start_min:
            raise ValueError("opening hours must end after they start (overnight hours: use two)")
        return self


def _placeholders(text: str, allowed: set[str], what: str) -> str:
    unknown = {m for m in PLACEHOLDER.findall(text)} - allowed
    if unknown:
        names = ", ".join(sorted(allowed)) or "none"
        raise ValueError(f"{what} can only use these placeholders: {names}")
    return text


class InboundSettings(BaseModel):
    always_open: bool = True
    hours: list[OpenWindow] = Field(default_factory=list, max_length=14)
    # Outside the hours the employee either takes a message (it answers, says the closed message
    # and listens) or does not answer at all (the caller is a missed caller).
    closed_mode: Literal["take_message", "hang_up"] = "take_message"
    closed_message: str = Field(default="", max_length=300)
    greeting_new: str = Field(default="", max_length=300)
    greeting_returning: str = Field(default="", max_length=300)
    disclosure: str = Field(default="", max_length=200)
    transfer_number: str | None = None
    transfer_when: str = Field(default="", max_length=300)
    auto_callback: bool = True
    daily_summary: bool = True
    # Instant and Bulk employees pick up when one of their leads calls back (the line is theirs).
    answer_callbacks: bool = True

    @field_validator("transfer_number")
    @classmethod
    def _transfer(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        match = INDIA_NUMBER.match(re.sub(r"[\s\-().]", "", value))
        if match is None:
            raise ValueError("the transfer number must be an Indian number: +91 and ten digits")
        return f"+91{match.group(1)}"

    @field_validator("greeting_new")
    @classmethod
    def _new(cls, value: str) -> str:
        return _placeholders(value, {"business_name"}, "the greeting for new callers")

    @field_validator("greeting_returning")
    @classmethod
    def _returning(cls, value: str) -> str:
        return _placeholders(value, NAME_PLACEHOLDERS, "the greeting for returning callers")

    @field_validator("closed_message", "disclosure")
    @classmethod
    def _plain(cls, value: str) -> str:
        return _placeholders(value, {"business_name"}, "this text")

    @model_validator(mode="after")
    def _consistent(self) -> "InboundSettings":
        if not self.always_open and not self.hours:
            raise ValueError("give at least one opening window, or answer 24/7")
        if self.transfer_number and not self.transfer_when.strip():
            raise ValueError("say when to transfer (for example: the caller asks for a person)")
        return self


def is_open(now: datetime, settings: InboundSettings) -> bool:
    """Whether the business is open at `now` (India time)."""
    if settings.always_open:
        return True
    here = local(now, IST)
    minute = here.hour * 60 + here.minute
    return any(
        here.weekday() in w.days and w.start_min <= minute < w.end_min for w in settings.hours
    )


def of(raw: dict[str, object] | None) -> InboundSettings:
    return InboundSettings.model_validate(raw or {})
