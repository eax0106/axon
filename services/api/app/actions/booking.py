"""Calendar booking: which times are free, and making one booking safely.

All times are Indian Standard Time (fixed UTC+5:30, see DECISIONS): the AI and the caller speak
IST and the calendar gets the offset with every time.
"""

import base64
import hashlib
import secrets
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from app.actions.schema import CalendarBooking
from app.providers.base import Busy, CalendarProvider

IST = timezone(timedelta(hours=5, minutes=30))
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def now() -> datetime:
    return datetime.now(IST)


def free_slots(cfg: CalendarBooking, day: date, now: datetime, busy: list[Busy]) -> list[datetime]:
    """Start times on `day` that are inside working time, far enough ahead, and not taken."""
    today = now.astimezone(IST).date()
    if not today <= day <= today + timedelta(days=cfg.days_ahead) or day.weekday() not in cfg.days:
        return []
    step = timedelta(minutes=cfg.duration_min)
    start = datetime.combine(day, time(cfg.start_hour), IST)
    end = datetime.combine(day, time(0), IST) + timedelta(hours=cfg.end_hour)
    earliest = now + timedelta(minutes=cfg.min_notice_min)
    slots = []
    while start + step <= end:
        taken = any(b.start < start + step and start < b.end for b in busy)
        if start >= earliest and not taken:
            slots.append(start)
        start += step
    return slots


def day_window(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(0), IST)
    return start, start + timedelta(days=1)


def event_id(call_key: str, start: datetime) -> str:
    """The same call booking the same time twice is one event: Google refuses a repeated id.
    (Event ids are base32hex, lowercase.)"""
    digest = hashlib.sha256(f"{call_key}|{start.isoformat()}".encode()).digest()
    return base64.b32hexencode(digest).decode().lower().rstrip("=")


def say(start: datetime) -> str:
    return f"{WEEKDAYS[start.weekday()]} {start.day} {start:%B %Y}, {start:%I:%M %p}".replace(
        " 0", " "
    )


async def availability(
    cfg: CalendarBooking, calendar: CalendarProvider, token: str, day: date, now: datetime
) -> list[datetime]:
    start, end = day_window(day)
    busy = await calendar.busy(token, cfg.calendar_id, start, end)
    return free_slots(cfg, day, now, busy)


async def book(
    cfg: CalendarBooking,
    calendar: CalendarProvider,
    token: str,
    start: datetime,
    now: datetime,
    *,
    call_key: str,
    description: str,
) -> dict[str, Any]:
    """Book `start` if it is one of the free slots right now (checked again here, not trusted from
    an earlier answer). The same booking made twice from one call is reported as done."""
    if start not in await availability(cfg, calendar, token, start.date(), now):
        return {"ok": False, "error": "that time is not free: check the free times again"}
    created = await calendar.create_event(
        token,
        cfg.calendar_id,
        event_id(call_key, start),
        cfg.title,
        description,
        start,
        start + timedelta(minutes=cfg.duration_min),
    )
    return {"ok": True, "booked": say(start), **({} if created else {"already": True})}


async def test_booking(
    cfg: CalendarBooking, calendar: CalendarProvider, token: str, now: datetime
) -> dict[str, Any]:
    """Prove the connection can write: book the first free time, then remove the event again."""
    today = now.astimezone(IST).date()
    key = f"test-{secrets.token_hex(8)}"
    for offset in range(cfg.days_ahead + 1):
        slots = await availability(cfg, calendar, token, today + timedelta(days=offset), now)
        if slots:
            note = "Axon test booking: removed at once."
            result = await book(cfg, calendar, token, slots[0], now, call_key=key, description=note)
            if result["ok"]:
                await calendar.delete_event(token, cfg.calendar_id, event_id(key, slots[0]))
            return result
    return {"ok": False, "error": f"no free time in the next {cfg.days_ahead} days"}
