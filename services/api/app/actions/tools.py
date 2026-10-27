"""The functions the AI can call during a call, built from an employee's actions.

A tool never raises: whatever goes wrong comes back as `{"ok": False, "error": ...}` in plain words
the AI can speak about. What a tool returns is data from another system and is fenced as such in
the prompt.
"""

import asyncio
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.actions import booking, http_tool
from app.actions.schema import (
    Action,
    CalendarBooking,
    HttpApi,
    Param,
    SheetRead,
    SheetWrite,
    WhatsApp,
)
from app.models import DncEntry, GoogleConnection
from app.providers.base import (
    CalendarProvider,
    ProviderKind,
    SheetsProvider,
    WhatsAppProvider,
)
from app.providers.registry import require

log = logging.getLogger("axon.actions")
INDIAN_MOBILE = re.compile(r"^\+91[6-9]\d{9}$")
MAX_CELL = 500
MAX_OFFERED = 12  # free times read out to the AI for one day
GRACE_S = 3.0  # a tool may take this much longer than its own timeout before it is cut off

Run = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    properties: dict[str, dict[str, str]]
    required: list[str]
    run: Run
    timeout_s: float = 15.0


@dataclass(frozen=True)
class ActionContext:
    """What a tool may know about the call it runs in. The caller's number is the only number a
    WhatsApp message can go to."""

    factory: async_sessionmaker[AsyncSession]
    account_id: uuid.UUID
    call_id: uuid.UUID | None = None
    party_phone: str | None = None
    party_name: str | None = None
    now: Callable[[], datetime] = booking.now  # India's clock; a test swaps it


def _clean(value: Any, limit: int = MAX_CELL) -> str:
    return " ".join("".join(c if c.isprintable() else " " for c in str(value)).split())[:limit]


def _schema(params: list[Param]) -> tuple[dict[str, dict[str, str]], list[str]]:
    props = {p.name: {"type": p.type, "description": p.description} for p in params}
    return props, [p.name for p in params if p.required]


def _values(params: list[Param], args: dict[str, Any]) -> tuple[list[str], str | None]:
    """The values in column order, or what is missing."""
    cells = []
    for param in params:
        value = args.get(param.name)
        if value in (None, ""):
            if param.required:
                return [], f"{param.name} is needed"
            value = ""
        cells.append(_clean(value))
    return cells, None


async def _token(ctx: ActionContext) -> str | None:
    async with ctx.factory() as session:
        connection = await session.get(GoogleConnection, ctx.account_id)
        return connection.refresh_token if connection else None


def _guarded(name: str, run: Run, timeout_s: float) -> Run:
    """Never raise, never run past the limit; say plainly that it failed."""

    async def safe(args: dict[str, Any]) -> dict[str, Any]:
        try:
            async with asyncio.timeout(timeout_s + GRACE_S):
                return await run(args)
        except Exception as exc:  # a failed tool must not end the call
            log.warning("action %s failed: %s", name, type(exc).__name__)
            return {"ok": False, "error": "that is not available right now"}

    return safe


def _http(action: HttpApi) -> list[Tool]:
    props, required = _schema(action.params)

    async def run(args: dict[str, Any]) -> dict[str, Any]:
        return await http_tool.call(action, args)

    return [Tool(action.name, action.description, props, required, run, action.timeout_s)]


def _calendar(action: CalendarBooking, ctx: ActionContext) -> list[Tool]:
    # Without a call id each tool set gets its own key, so two calls never share event ids.
    call_key = str(ctx.call_id or uuid.uuid4())
    booked: set[datetime] = set()  # the same time asked for twice in one call is one event

    async def parts() -> tuple[CalendarProvider, str] | dict[str, Any]:
        token = await _token(ctx)
        if token is None:
            return {"ok": False, "error": "the calendar is not connected"}
        provider = require(ProviderKind.CALENDAR)
        assert isinstance(provider, CalendarProvider)
        return provider, token

    async def free(args: dict[str, Any]) -> dict[str, Any]:
        try:
            day = date.fromisoformat(str(args.get("date", "")))
        except ValueError:
            return {"ok": False, "error": "date must be written YYYY-MM-DD"}
        got = await parts()
        if isinstance(got, dict):
            return got
        slots = (await booking.availability(action, *got, day, ctx.now()))[:MAX_OFFERED]
        return {
            "ok": True,
            "date": day.isoformat(),
            "weekday": booking.WEEKDAYS[day.weekday()],
            "free_times": [f"{s:%H:%M}" for s in slots],
        }

    async def book(args: dict[str, Any]) -> dict[str, Any]:
        try:
            start = datetime.fromisoformat(str(args.get("start", "")))
            start = (
                start.astimezone(booking.IST) if start.tzinfo else start.replace(tzinfo=booking.IST)
            )
        except ValueError:
            return {"ok": False, "error": "start must be written YYYY-MM-DD HH:MM"}
        name = _clean(args.get("name", ""), 100)
        if not name:
            return {"ok": False, "error": "the caller's name is needed"}
        if start in booked:
            return {"ok": True, "booked": booking.say(start), "already": True}
        got = await parts()
        if isinstance(got, dict):
            return got
        note = (
            f"Booked by the AI phone employee.\nName: {name}\nPhone: {ctx.party_phone or 'unknown'}"
        )
        result = await booking.book(
            action, *got, start, ctx.now(),
            call_key=call_key, description=note,
        )  # fmt: skip
        if result["ok"]:
            booked.add(start)
        return result

    day = Param(name="date", description="The day, written YYYY-MM-DD")
    first = Tool(
        f"{action.name}_availability",
        f"{action.description} Lists the free times on one day.",
        *_schema([day]),
        free,
    )
    second = Param(name="start", description="The chosen time in India, written YYYY-MM-DD HH:MM")
    person = Param(name="name", description="The caller's name")
    return [
        first,
        Tool(
            f"{action.name}_book",
            f"{action.description} Books one of the free times.",
            *_schema([second, person]),
            book,
        ),
    ]


def _sheet_read(action: SheetRead, ctx: ActionContext) -> list[Tool]:
    async def run(args: dict[str, Any]) -> dict[str, Any]:
        lookup = _clean(args.get("lookup", ""), 100).lower()
        if not lookup:
            return {"ok": False, "error": "say what to look for"}
        token = await _token(ctx)
        if token is None:
            return {"ok": False, "error": "Google is not connected"}
        sheets = require(ProviderKind.SHEETS)
        assert isinstance(sheets, SheetsProvider)
        # shortcut: reads the whole range on every lookup; cache or index it for sheets beyond a
        # few thousand rows.
        rows = await sheets.read_rows(token, action.sheet_id, action.range)
        if not rows:
            return {"ok": True, "columns": [], "rows": []}
        found = [r for r in rows[1:] if lookup in " ".join(r).lower()][: action.max_rows]
        return {
            "ok": True,
            "columns": [_clean(c, 100) for c in rows[0]],
            "rows": [[_clean(c) for c in r] for r in found],
        }

    props, required = _schema([Param(name="lookup", description="The text to look for")])
    return [Tool(action.name, action.description, props, required, run)]


def _sheet_write(action: SheetWrite, ctx: ActionContext) -> list[Tool]:
    written: set[tuple[str, ...]] = set()  # the same row asked for twice in one call is one row

    async def run(args: dict[str, Any]) -> dict[str, Any]:
        values, problem = _values(action.columns, args)
        if problem:
            return {"ok": False, "error": problem}
        cells = values
        if action.include_call_details:
            stamp = ctx.now().strftime("%Y-%m-%d %H:%M")
            cells = [stamp, ctx.party_phone or "", *values]
        key = tuple(values)
        if key in written:
            return {"ok": True, "saved": True, "already": True}
        token = await _token(ctx)
        if token is None:
            return {"ok": False, "error": "Google is not connected"}
        sheets = require(ProviderKind.SHEETS)
        assert isinstance(sheets, SheetsProvider)
        await sheets.append_row(token, action.sheet_id, action.range, cells)
        written.add(key)
        return {"ok": True, "saved": True}

    return [Tool(action.name, action.description, *_schema(action.columns), run)]


def _whatsapp(action: WhatsApp, ctx: ActionContext) -> list[Tool]:
    sent: set[tuple[str, ...]] = set()  # one message per call for the same words

    async def run(args: dict[str, Any]) -> dict[str, Any]:
        phone = ctx.party_phone or ""
        if not INDIAN_MOBILE.match(phone):
            return {"ok": False, "error": "there is no WhatsApp number for this caller"}
        values, problem = _values(action.params, args)
        if problem:
            return {"ok": False, "error": problem}
        if tuple(values) in sent:
            return {"ok": True, "sent": True, "already": True}
        async with ctx.factory() as session:
            blocked = await session.scalar(
                select(DncEntry.id).where(
                    DncEntry.account_id == ctx.account_id, DncEntry.phone == phone
                )
            )
        if blocked:
            return {"ok": False, "error": "this person asked not to be contacted"}
        provider = require(ProviderKind.WHATSAPP)
        assert isinstance(provider, WhatsAppProvider)
        await provider.send_template(
            phone, action.template, action.language, values, ctx.party_name or ""
        )
        sent.add(tuple(values))
        return {"ok": True, "sent": True}

    return [Tool(action.name, action.description, *_schema(action.params), run)]


def build_tools(actions: list[Action], ctx: ActionContext, *, guarded: bool = True) -> list[Tool]:
    """One tool per action (two for a calendar). On a call each is wrapped so that it cannot fail
    loudly; the owner's test console asks for them unwrapped to see why one failed."""
    tools: list[Tool] = []
    for action in actions:
        if isinstance(action, HttpApi):
            made = _http(action)
        elif isinstance(action, CalendarBooking):
            made = _calendar(action, ctx)
        elif isinstance(action, SheetRead):
            made = _sheet_read(action, ctx)
        elif isinstance(action, SheetWrite):
            made = _sheet_write(action, ctx)
        else:
            made = _whatsapp(action, ctx)
        tools += [
            Tool(
                t.name, t.description, t.properties, t.required,
                _guarded(t.name, t.run, t.timeout_s) if guarded else t.run, t.timeout_s,
            )
            for t in made
        ]  # fmt: skip
    return tools


async def run_timed(tool: Tool, args: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Run a tool; the answer and how many milliseconds it took."""
    started = time.monotonic()
    result = await tool.run(args)
    return result, round((time.monotonic() - started) * 1000)
