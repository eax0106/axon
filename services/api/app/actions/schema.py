"""What an employee may do during a call, as the owner writes it. Actions live in the script
bundle, so they share its publish gate, its versions and its restore. Every one is opt-in: an
employee has none until the owner adds them.

A secret (an API token) is stored with the action but never sent back: reads show MASK, and
sending MASK back keeps the stored secret.
"""

import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator

from app.actions import net

IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
RESERVED = {"end_call", "transfer_to_human"}  # tools the engine already has
MASK = "********"
MAX_ACTIONS = 10
_HEADER = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,39}$")
_FORBIDDEN_HEADERS = {
    "host", "content-length", "content-type", "authorization", "cookie", "connection",
    "transfer-encoding", "upgrade", "te", "trailer", "proxy-authorization",
}  # fmt: skip
_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")
_SHEET_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
_RANGE = re.compile(r"^[^\x00-\x1f]{1,100}$")
_CALENDAR_ID = re.compile(r"^[A-Za-z0-9._@%+-]{1,200}$")
_TEMPLATE = re.compile(r"^[A-Za-z0-9_ -]{1,100}$")
_LANGUAGE = re.compile(r"^[a-z]{2}(_[A-Z]{2})?$")


def _identifier(value: str) -> str:
    if not IDENTIFIER.match(value):
        raise ValueError("use lowercase letters, digits and underscores, starting with a letter")
    return value


def _match(pattern: re.Pattern[str], value: str, what: str) -> str:
    if not pattern.match(value):
        raise ValueError(f"not a valid {what}")
    return value


class Param(BaseModel):
    """One value the AI must supply when it uses the action."""

    name: str = Field(max_length=40)
    description: str = Field(min_length=1, max_length=200)
    type: Literal["string", "number", "boolean"] = "string"
    required: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _identifier(value)


def _unique(params: list[Param]) -> list[Param]:
    if len({p.name for p in params}) != len(params):
        raise ValueError("duplicate parameter name")
    return params


class _Action(BaseModel):
    name: str = Field(max_length=40)
    # The owner's words to the AI about when to use it; they become the tool's description.
    description: str = Field(min_length=1, max_length=300)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _identifier(value)


class HttpAuth(BaseModel):
    kind: Literal["none", "bearer", "header"] = "none"
    header: str = Field(default="", max_length=40)  # the header's name, for kind "header"
    secret: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def _complete(self) -> "HttpAuth":
        if self.kind != "none" and not self.secret:
            raise ValueError("a secret is needed")
        if self.kind == "header":
            _match(_HEADER, self.header, "header name")
            if self.header.lower() in _FORBIDDEN_HEADERS:
                raise ValueError(f"the {self.header} header is set for you")
        if "\r" in self.secret or "\n" in self.secret:
            raise ValueError("a secret is one line")
        return self


class HttpApi(_Action):
    """Call the owner's own web service. Values for `{name}` in the URL go in the path or query;
    the rest go in the query (GET, DELETE) or a JSON body (POST, PUT, PATCH)."""

    kind: Literal["http_api"] = "http_api"
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "GET"
    url: str = Field(max_length=500)
    params: list[Param] = Field(default_factory=list, max_length=10)
    headers: dict[str, str] = Field(default_factory=dict, max_length=10)
    auth: HttpAuth = Field(default_factory=HttpAuth)
    timeout_s: int = Field(default=8, ge=1, le=15)

    _params = field_validator("params")(_unique)

    @field_validator("url")
    @classmethod
    def _url(cls, value: str) -> str:
        problem = net.url_problem(value)
        if problem:
            raise ValueError(problem)
        return value

    @field_validator("headers")
    @classmethod
    def _headers(cls, headers: dict[str, str]) -> dict[str, str]:
        for key, value in headers.items():
            _match(_HEADER, key, "header name")
            if key.lower() in _FORBIDDEN_HEADERS:
                raise ValueError(f"the {key} header is set for you")
            if len(value) > 500 or not value.isprintable():
                raise ValueError(f"the value of {key} must be one printable line")
        return headers

    @model_validator(mode="after")
    def _placeholders(self) -> "HttpApi":
        unknown = set(_PLACEHOLDER.findall(self.url)) - {p.name for p in self.params}
        if unknown:
            raise ValueError(f"the URL uses {{{sorted(unknown)[0]}}} which is not a parameter")
        return self


class CalendarBooking(_Action):
    """Offer free times and book one on the owner's Google Calendar, in Indian time."""

    kind: Literal["calendar_booking"] = "calendar_booking"
    calendar_id: str = Field(default="primary", max_length=200)
    duration_min: int = Field(default=30, ge=10, le=240)
    days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 5], min_length=1)  # Monday = 0
    start_hour: int = Field(default=10, ge=0, le=23)
    end_hour: int = Field(default=18, ge=1, le=24)
    min_notice_min: int = Field(default=60, ge=0, le=10080)
    days_ahead: int = Field(default=14, ge=1, le=60)
    title: str = Field(default="Appointment", min_length=1, max_length=100)

    @field_validator("calendar_id")
    @classmethod
    def _calendar(cls, value: str) -> str:
        return _match(_CALENDAR_ID, value, "calendar id")

    @field_validator("days")
    @classmethod
    def _days(cls, days: list[int]) -> list[int]:
        if any(not 0 <= d <= 6 for d in days) or len(set(days)) != len(days):
            raise ValueError("days are distinct numbers from 0 (Monday) to 6 (Sunday)")
        return sorted(days)

    @model_validator(mode="after")
    def _hours(self) -> "CalendarBooking":
        if (self.end_hour - self.start_hour) * 60 < self.duration_min:
            raise ValueError("the working hours are shorter than one appointment")
        return self


class SheetRead(_Action):
    """Look a value up in a Google Sheet: the rows that contain what the AI asks for."""

    kind: Literal["sheet_read"] = "sheet_read"
    sheet_id: str
    range: str = "A:Z"
    max_rows: int = Field(default=5, ge=1, le=20)

    @field_validator("sheet_id")
    @classmethod
    def _sheet(cls, value: str) -> str:
        return _match(_SHEET_ID, value, "sheet id")

    @field_validator("range")
    @classmethod
    def _range(cls, value: str) -> str:
        return _match(_RANGE, value, "range")


class SheetWrite(_Action):
    """Add a row to a Google Sheet, one column per value the AI fills in."""

    kind: Literal["sheet_write"] = "sheet_write"
    sheet_id: str
    range: str = "A:Z"
    columns: list[Param] = Field(min_length=1, max_length=15)
    include_call_details: bool = True  # the time of the call and the caller's number come first

    _columns = field_validator("columns")(_unique)
    _sheet = field_validator("sheet_id")(lambda v: _match(_SHEET_ID, v, "sheet id"))
    _range = field_validator("range")(lambda v: _match(_RANGE, v, "range"))


class WhatsApp(_Action):
    """Send an approved WhatsApp template to the person on the call, and to nobody else."""

    kind: Literal["whatsapp"] = "whatsapp"
    template: str  # Interakt: the template's code name; AiSensy: the live API campaign's name
    language: str = "en"
    params: list[Param] = Field(default_factory=list, max_length=10)  # fill {{1}}, {{2}} in order

    _params = field_validator("params")(_unique)
    _template = field_validator("template")(lambda v: _match(_TEMPLATE, v, "template name"))
    _language = field_validator("language")(lambda v: _match(_LANGUAGE, v, "language code"))


ActionConfig = Annotated[
    HttpApi | CalendarBooking | SheetRead | SheetWrite | WhatsApp, Field(discriminator="kind")
]
Action = HttpApi | CalendarBooking | SheetRead | SheetWrite | WhatsApp


def tool_names(action: Action) -> list[str]:
    """The functions the AI gets for one action."""
    if isinstance(action, CalendarBooking):
        return [f"{action.name}_availability", f"{action.name}_book"]
    return [action.name]


def check_names(actions: list[Action]) -> list[Action]:
    names = [n for a in actions for n in tool_names(a)]
    if len(set(names)) != len(names) or len({a.name for a in actions}) != len(actions):
        raise ValueError("every action needs its own name")
    if clash := set(names) & RESERVED:
        raise ValueError(f"{sorted(clash)[0]} is a name the call already uses")
    return actions


def mask(actions: list[Action]) -> list[Action]:
    """Copies safe to send out: secrets replaced by MASK."""
    return [
        a.model_copy(update={"auth": a.auth.model_copy(update={"secret": MASK})})
        if isinstance(a, HttpApi) and a.auth.secret
        else a
        for a in actions
    ]


def keep_secrets(incoming: list[Action], stored: list[Action]) -> list[Action]:
    """Put back the stored secret wherever the caller sent MASK. A mask with nothing stored under
    that name is refused: it would save the word MASK as a password. So is a mask on an action
    that now points at another host: the secret was given for the old one."""
    old = {a.name: a for a in stored if isinstance(a, HttpApi)}
    kept: list[Action] = []
    for action in incoming:
        if isinstance(action, HttpApi) and action.auth.secret == MASK:
            before = old.get(action.name)
            if before is None or not before.auth.secret:
                raise ValueError(f"send the secret for {action.name} again")
            if urlsplit(action.url).netloc.lower() != urlsplit(before.url).netloc.lower():
                raise ValueError(f"send the secret for {action.name} again: its host changed")
            action = action.model_copy(
                update={"auth": action.auth.model_copy(update={"secret": before.auth.secret})}
            )
        kept.append(action)
    return kept
