"""What an employee is made of: the script bundle (publish-gated) and the settings (instant)."""

import re
import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator

IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
AMBIENCES = ("none", "office", "call_center", "restaurant", "quiet_room", "retail_store")
LANGUAGES = ("te", "hi", "en")
# The bundle is also stored as JSON in employee_versions, so keep it small and bounded.
MAX_SECTIONS, MAX_FAQ, MAX_VARIABLES, MAX_CAPTURE = 20, 50, 30, 20


def _identifier(value: str) -> str:
    if not IDENTIFIER.match(value):
        raise ValueError("use lowercase letters, digits and underscores, starting with a letter")
    return value


class Section(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12], max_length=40)
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(max_length=4000)


class FaqItem(BaseModel):
    question: str = Field(min_length=1, max_length=300)
    answer: str = Field(min_length=1, max_length=1500)


class ScriptBundle(BaseModel):
    """Everything a caller can hear as content. Editing it needs a publish to reach live calls.

    The FAQ is a permanent part of the bundle: it can be emptied but never removed.
    """

    welcome_message: str = Field(default="", max_length=500)
    agent_information: str = Field(default="", max_length=4000)
    sections: list[Section] = Field(default_factory=list, max_length=MAX_SECTIONS)
    end_rules: str = Field(default="", max_length=2000)
    faq: list[FaqItem] = Field(default_factory=list, max_length=MAX_FAQ)
    strictness: int = Field(default=3, ge=1, le=5)
    pre_call_variables: list[str] = Field(default_factory=list, max_length=MAX_VARIABLES)

    @field_validator("pre_call_variables")
    @classmethod
    def _variables(cls, names: list[str]) -> list[str]:
        if len(set(names)) != len(names):
            raise ValueError("duplicate variable name")
        return [_identifier(name) for name in names]

    @field_validator("sections")
    @classmethod
    def _unique_ids(cls, sections: list[Section]) -> list[Section]:
        if len({s.id for s in sections}) != len(sections):
            raise ValueError("duplicate section id")
        return sections


class CaptureField(BaseModel):
    name: str = Field(max_length=40)
    description: str = Field(min_length=1, max_length=300)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _identifier(value)


class EmployeeSettings(BaseModel):
    """Delivery and bookkeeping: applied to live calls at once, never part of the content."""

    tts_speed: float = Field(default=1.0, ge=0.5, le=2.0)
    ambience: Literal[
        "none", "office", "call_center", "restaurant", "quiet_room", "retail_store"
    ] = "none"
    ambience_volume: float = Field(default=0.3, ge=0.0, le=1.0)
    style_pack: bool = False
    power_prompting: bool = False
    ai_acknowledgement: bool = False
    capture: list[CaptureField] = Field(default_factory=list, max_length=MAX_CAPTURE)

    @field_validator("capture")
    @classmethod
    def _unique_names(cls, fields: list[CaptureField]) -> list[CaptureField]:
        if len({f.name for f in fields}) != len(fields):
            raise ValueError("duplicate capture field name")
        return fields
