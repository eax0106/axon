"""The account's Google connection, and whether the actions an employee has can use it."""

import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.actions.schema import Action, CalendarBooking, SheetRead, SheetWrite, keep_secrets
from app.models import GoogleConnection, Role, User
from app.providers.google import calendar, sheets

CALENDAR_SCOPE = calendar.SCOPES[0]
SHEETS_SCOPE = sheets.WRITE_SCOPE
SERVICE_SCOPES = {"calendar": calendar.SCOPES, "sheets": (sheets.WRITE_SCOPE,)}


def services_of(connection: GoogleConnection | None) -> dict[str, bool]:
    scopes = set(connection.scopes) if connection else set()
    return {"calendar": CALENDAR_SCOPE in scopes, "sheets": SHEETS_SCOPE in scopes}


def needed(actions: list[Action]) -> set[str]:
    wanted = set()
    for action in actions:
        if isinstance(action, CalendarBooking):
            wanted.add("calendar")
        elif isinstance(action, SheetRead | SheetWrite):
            wanted.add("sheets")
    return wanted


async def missing(session: AsyncSession, account_id: uuid.UUID, actions: list[Action]) -> list[str]:
    """The Google services the actions need that the account has not allowed."""
    wanted = needed(actions)
    if not wanted:
        return []
    have = services_of(await session.get(GoogleConnection, account_id))
    return sorted(s for s in wanted if not have[s])


def _sheets_changed(incoming: list[Action], stored: list[Action]) -> bool:
    before = [a for a in stored if isinstance(a, SheetRead | SheetWrite)]
    return [a for a in incoming if isinstance(a, SheetRead | SheetWrite)] != before


async def accept(
    session: AsyncSession, user: User, incoming: list[Action], stored: list[Action]
) -> list[Action]:
    """An edited list of actions as it should be stored: secrets the caller left masked are put
    back, an action that needs Google the account has not allowed is refused, and only the owner
    may point an action at a spreadsheet, since it is read with the owner's Google account."""
    account_id = user.account_id
    if user.role != Role.OWNER and _sheets_changed(incoming, stored):
        raise HTTPException(
            403, "only the account owner can change which spreadsheet an action uses"
        )
    try:
        kept = keep_secrets(incoming, stored)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    lacking = await missing(session, account_id, kept)
    if lacking:
        raise HTTPException(409, f"connect Google {' and '.join(lacking)} first")
    return kept
