"""The account's do-not-call list. Anyone in the account may add a number (it only ever stops
calls); only the owner may take one off. A number on the list is never dialed: every dialer checks
it just before the call, and adding a number cancels the calls already waiting for it."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.db import Session
from app.employees.router import OwnerUser
from app.instant.intake import normalize_phone
from app.models import Call, CallStatus, DncEntry, DncSource, Lead

router = APIRouter(prefix="/dnc")
BULK_MAX = 10_000
CHUNK = 1_000  # rows per insert: Postgres takes at most 32767 parameters a statement


class DncIn(BaseModel):
    phone: str = Field(max_length=40)
    reason: str | None = Field(default=None, max_length=500)


class DncBulkIn(BaseModel):
    phones: list[str] = Field(min_length=1, max_length=BULK_MAX)
    reason: str | None = Field(default=None, max_length=500)


class DncOut(BaseModel):
    id: uuid.UUID
    phone: str
    source: DncSource
    reason: str | None
    created_at: datetime


def _out(entry: DncEntry) -> DncOut:
    return DncOut(
        id=entry.id,
        phone=entry.phone,
        source=entry.source,
        reason=entry.reason,
        created_at=entry.created_at,
    )


async def _cancel_waiting(session: AsyncSession, account_id: uuid.UUID, phones: list[str]) -> None:
    """Calls queued for these numbers will not ring now."""
    leads = select(Lead.id).where(Lead.account_id == account_id, Lead.phone.in_(phones))
    await session.execute(
        update(Call)
        .where(
            Call.account_id == account_id,
            Call.status == CallStatus.QUEUED,
            Call.lead_id.in_(leads.scalar_subquery()),
        )
        .values(status=CallStatus.CANCELED)
    )


async def _add(
    session: AsyncSession,
    account_id: uuid.UUID,
    phones: list[str],
    source: DncSource,
    reason: str | None,
) -> int:
    """Insert the numbers not listed yet; returns how many were added."""
    added = 0
    for at in range(0, len(phones), CHUNK):
        rows = [
            {"account_id": account_id, "phone": p, "source": source, "reason": reason}
            for p in phones[at : at + CHUNK]
        ]
        inserted = await session.scalars(
            insert(DncEntry).values(rows).on_conflict_do_nothing().returning(DncEntry.id)
        )
        added += len(inserted.all())
    await _cancel_waiting(session, account_id, phones)
    return added


@router.get("")
async def list_dnc(
    user: CurrentUser,
    session: Session,
    q: Annotated[str | None, Query(max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    query = select(DncEntry).where(DncEntry.account_id == user.account_id)
    if q and (digits := "".join(c for c in q if c.isdigit())):
        query = query.where(DncEntry.phone.contains(digits, autoescape=True))
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.scalars(
        query.order_by(DncEntry.created_at.desc(), DncEntry.id).limit(limit).offset(offset)
    )
    return {
        "total": total or 0,
        "limit": limit,
        "offset": offset,
        "items": [_out(r) for r in rows],
    }


@router.post("")
async def add_dnc(body: DncIn, user: CurrentUser, session: Session, response: Response) -> DncOut:
    """Add one number. Adding a number already listed changes nothing (200 instead of 201)."""
    phone = normalize_phone(body.phone)
    if phone is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "not an Indian mobile number")
    added = await _add(session, user.account_id, [phone], DncSource.MANUAL, body.reason)
    await session.commit()
    response.status_code = status.HTTP_201_CREATED if added else status.HTTP_200_OK
    entry = await session.scalar(
        select(DncEntry).where(DncEntry.account_id == user.account_id, DncEntry.phone == phone)
    )
    assert entry is not None
    return _out(entry)


@router.post("/bulk")
async def add_dnc_bulk(body: DncBulkIn, user: CurrentUser, session: Session) -> dict[str, int]:
    """Add many numbers at once (pasted or from a file). Says how many were added, how many were
    listed already and how many were not phone numbers."""
    phones = [normalize_phone(p) for p in body.phones]
    valid = sorted({p for p in phones if p is not None})
    added = await _add(session, user.account_id, valid, DncSource.BULK, body.reason)
    await session.commit()
    return {
        "added": added,
        "already_listed": len(valid) - added,
        "invalid": phones.count(None),
    }


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_dnc(entry_id: uuid.UUID, user: OwnerUser, session: Session) -> None:
    entry = await session.get(DncEntry, entry_id)
    if entry is None or entry.account_id != user.account_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not on the list")
    await session.delete(entry)
    await session.commit()
