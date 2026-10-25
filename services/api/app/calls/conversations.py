"""Conversations: every call, filtered, exported, opened up, with notes."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.calls import postcall
from app.calls.csvsafe import to_csv
from app.db import Session
from app.models import Call, Employee, Lead, Note, Role, User
from app.providers.base import ObjectStorageProvider, ProviderKind
from app.providers.registry import require

router = APIRouter()
EXPORT_LIMIT = 10_000
RECORDING_LINK_TTL_S = 900


class CallFilters(BaseModel):
    """Also what a user's remembered conversation filters are made of."""

    outcome: str | None = None
    sentiment: str | None = None
    employee_id: uuid.UUID | None = None
    channel: str | None = None
    campaign_id: uuid.UUID | None = None
    direction: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    min_duration: int | None = Field(default=None, ge=0)
    max_duration: int | None = Field(default=None, ge=0)
    min_credits: float | None = Field(default=None, ge=0)
    max_credits: float | None = Field(default=None, ge=0)
    include_test: bool = False
    q: str | None = Field(default=None, max_length=100)


def filters(
    outcome: str | None = None,
    sentiment: str | None = None,
    employee_id: uuid.UUID | None = None,
    channel: str | None = None,
    campaign_id: uuid.UUID | None = None,
    direction: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    min_duration: Annotated[int | None, Query(ge=0)] = None,
    max_duration: Annotated[int | None, Query(ge=0)] = None,
    min_credits: Annotated[float | None, Query(ge=0)] = None,
    max_credits: Annotated[float | None, Query(ge=0)] = None,
    include_test: bool = False,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> CallFilters:
    return CallFilters(**{k: v for k, v in locals().items()})


Filters = Annotated[CallFilters, Depends(filters)]


def apply(query: Select[Any], account_id: uuid.UUID, f: CallFilters) -> Select[Any]:
    query = query.where(Call.account_id == account_id)
    if not f.include_test:
        query = query.where(Call.is_test.is_(False))
    exact = {
        Call.outcome: f.outcome,
        Call.sentiment: f.sentiment,
        Call.employee_id: f.employee_id,
        Call.channel: f.channel,
        Call.campaign_id: f.campaign_id,
        Call.direction: f.direction,
    }
    for column, value in exact.items():
        if value is not None:
            query = query.where(column == value)
    if f.date_from:
        query = query.where(Call.created_at >= f.date_from)
    if f.date_to:
        query = query.where(Call.created_at < f.date_to)
    if f.min_duration is not None:
        query = query.where(Call.duration_s >= f.min_duration)
    if f.max_duration is not None:
        query = query.where(Call.duration_s <= f.max_duration)
    if f.min_credits is not None:
        query = query.where(Call.credits_charged >= f.min_credits)
    if f.max_credits is not None:
        query = query.where(Call.credits_charged <= f.max_credits)
    if f.q:
        like = f"%{f.q.strip()}%"
        query = query.where(or_(Lead.phone.ilike(like), Lead.name.ilike(like)))
    return query


Joined = tuple[Call, str | None, str | None, str | None]


class CallRow(BaseModel):
    id: uuid.UUID
    created_at: datetime
    employee_id: uuid.UUID | None
    employee_name: str | None
    lead_id: uuid.UUID | None
    phone: str | None
    name: str | None
    direction: str
    channel: str
    status: str
    outcome: str | None
    sentiment: str | None
    duration_s: int | None
    credits_charged: float
    summary: str | None
    is_test: bool
    analysis_status: str | None


def _joined() -> Select[Any]:
    query: Any = (
        select(Call, Employee.name, Lead.phone, Lead.name)
        .join(Employee, Employee.id == Call.employee_id, isouter=True)
        .join(Lead, Lead.id == Call.lead_id, isouter=True)
    )
    return query  # type: ignore[no-any-return]


async def fetch(session: AsyncSession, query: Select[Any]) -> list[Joined]:
    return [(r[0], r[1], r[2], r[3]) for r in (await session.execute(query)).all()]


def _row(
    call: Call, employee_name: str | None, phone: str | None, lead_name: str | None
) -> CallRow:
    return CallRow(
        id=call.id,
        created_at=call.created_at,
        employee_id=call.employee_id,
        employee_name=employee_name,
        lead_id=call.lead_id,
        phone=phone,
        name=lead_name,
        direction=call.direction.value,
        channel=call.channel.value,
        status=call.status.value,
        outcome=call.outcome,
        sentiment=call.sentiment,
        duration_s=call.duration_s,
        credits_charged=float(call.credits_charged),
        summary=call.summary,
        is_test=call.is_test,
        analysis_status=call.analysis_status,
    )


@router.get("/calls")
async def list_calls(
    user: CurrentUser,
    session: Session,
    f: Filters,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    base = apply(_joined(), user.account_id, f)
    total = await session.scalar(select(func.count()).select_from(base.order_by(None).subquery()))
    rows = await fetch(session, base.order_by(Call.created_at.desc()).limit(limit).offset(offset))
    return {
        "total": total or 0,
        "limit": limit,
        "offset": offset,
        "items": [_row(*r) for r in rows],
    }


EXPORT_COLUMNS = (
    "time",
    "employee",
    "phone",
    "name",
    "direction",
    "channel",
    "status",
    "outcome",
    "sentiment",
    "duration_s",
    "credits",
    "summary",
)


@router.get("/calls/export.csv")
async def export_calls(user: CurrentUser, session: Session, f: Filters) -> Response:
    query = (
        apply(_joined(), user.account_id, f).order_by(Call.created_at.desc()).limit(EXPORT_LIMIT)
    )
    rows = await fetch(session, query)
    body = to_csv(
        EXPORT_COLUMNS,
        (
            (
                c.created_at.isoformat(),
                employee,
                phone,
                lead_name,
                c.direction.value,
                c.channel.value,
                c.status.value,
                c.outcome,
                c.sentiment,
                c.duration_s,
                c.credits_charged,
                c.summary,
            )
            for c, employee, phone, lead_name in rows
        ),
    )
    return Response(
        body,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=calls.csv"},
    )


@router.get("/me/filters/conversations")
async def get_saved_filters(user: CurrentUser) -> CallFilters:
    return CallFilters.model_validate((user.ui_prefs or {}).get("conversation_filters") or {})


@router.put("/me/filters/conversations")
async def put_saved_filters(body: CallFilters, user: CurrentUser, session: Session) -> CallFilters:
    """Remember a user's conversation filters (the dashboard reloads them next time)."""
    stored = await session.get(User, user.id)
    assert stored is not None  # the token's user exists
    stored.ui_prefs = {
        **(stored.ui_prefs or {}),
        "conversation_filters": body.model_dump(mode="json"),
    }
    await session.commit()
    return body


async def own_call(session: AsyncSession, user: User, call_id: uuid.UUID) -> Call:
    call = await session.scalar(
        select(Call).where(Call.id == call_id, Call.account_id == user.account_id)
    )
    if call is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "call not found")
    return call


class NoteOut(BaseModel):
    id: uuid.UUID
    body: str
    created_at: datetime
    call_id: uuid.UUID | None
    user_id: uuid.UUID | None


def note_out(n: Note) -> NoteOut:
    return NoteOut(
        id=n.id, body=n.body, created_at=n.created_at, call_id=n.call_id, user_id=n.user_id
    )


def _timeline(call: Call, events: list[Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = [
        {"at": e.at.isoformat(), "type": e.type, "data": e.data} for e in events
    ]
    for turn in call.transcript:
        kind = "caller_said" if turn.get("role") == "user" else "agent_said"
        items.append({"at": turn.get("at"), "type": kind, "data": {"text": turn.get("text", "")}})
    floor = datetime.min.replace(tzinfo=UTC).isoformat()
    return sorted(items, key=lambda i: i["at"] or floor)


@router.get("/calls/{call_id}")
async def call_detail(call_id: uuid.UUID, user: CurrentUser, session: Session) -> dict[str, Any]:
    from app.models import CallEvent

    call = await own_call(session, user, call_id)
    row = (await fetch(session, _joined().where(Call.id == call.id)))[0]
    events = list(
        await session.scalars(
            select(CallEvent).where(CallEvent.call_id == call.id).order_by(CallEvent.id)
        )
    )
    notes = list(
        await session.scalars(select(Note).where(Note.call_id == call.id).order_by(Note.created_at))
    )
    return {
        **_row(*row).model_dump(),
        "started_at": call.started_at,
        "answered_at": call.answered_at,
        "ended_at": call.ended_at,
        "transcript": call.transcript,
        "captured": call.captured,
        "analysis_error": call.analysis_error,
        "is_callback": call.is_callback,
        "attempt": call.attempt,
        "has_recording": call.recording_key is not None,
        "timeline": _timeline(call, events),
        "notes": [note_out(n).model_dump() for n in notes],
    }


@router.get("/calls/{call_id}/recording")
async def call_recording(call_id: uuid.UUID, user: CurrentUser, session: Session) -> dict[str, Any]:
    call = await own_call(session, user, call_id)
    if call.recording_key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "this call has no recording")
    storage = require(ProviderKind.STORAGE)
    assert isinstance(storage, ObjectStorageProvider)
    return {
        "url": storage.presigned_url(call.recording_key, RECORDING_LINK_TTL_S),
        "expires_in": RECORDING_LINK_TTL_S,
    }


@router.get("/calls/{call_id}/share-text")
async def share_text(call_id: uuid.UUID, user: CurrentUser, session: Session) -> Response:
    """The call in a few plain lines, to paste into a message. Nothing is published."""
    call = await own_call(session, user, call_id)
    _, employee, phone, name = (await fetch(session, _joined().where(Call.id == call.id)))[0]
    lines = [
        f"Call with {name or phone or 'a caller'}" + (f" ({phone})" if name and phone else ""),
        f"By {employee or 'an AI employee'} on "
        f"{call.created_at.astimezone(UTC):%d %b %Y, %H:%M} UTC",
        f"Outcome: {call.outcome or 'not analysed yet'}"
        + (f" | Sentiment: {call.sentiment}" if call.sentiment else ""),
    ]
    if call.summary:
        lines += ["", call.summary]
    for key, value in call.captured.items():
        lines.append(f"{key}: {value}")
    return Response("\n".join(lines) + "\n", media_type="text/plain; charset=utf-8")


@router.post("/calls/{call_id}/reanalyze", status_code=status.HTTP_202_ACCEPTED)
async def reanalyze(call_id: uuid.UUID, user: CurrentUser, session: Session) -> dict[str, str]:
    call = await own_call(session, user, call_id)
    if not await postcall.reanalyze(session, call):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "only a skipped or failed analysis can be run again"
        )
    await session.commit()
    return {"analysis_status": "pending"}


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


@router.get("/calls/{call_id}/notes")
async def call_notes(call_id: uuid.UUID, user: CurrentUser, session: Session) -> list[NoteOut]:
    call = await own_call(session, user, call_id)
    rows = await session.scalars(
        select(Note).where(Note.call_id == call.id).order_by(Note.created_at)
    )
    return [note_out(n) for n in rows]


@router.post("/calls/{call_id}/notes", status_code=status.HTTP_201_CREATED)
async def add_call_note(
    call_id: uuid.UUID, body: NoteIn, user: CurrentUser, session: Session
) -> NoteOut:
    call = await own_call(session, user, call_id)
    note = Note(
        account_id=user.account_id,
        call_id=call.id,
        lead_id=call.lead_id,
        user_id=user.id,
        body=body.body.strip(),
    )
    session.add(note)
    await session.commit()
    return note_out(note)


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(note_id: uuid.UUID, user: CurrentUser, session: Session) -> None:
    """The author, or the account owner, may remove a note."""
    note = await session.scalar(
        select(Note).where(Note.id == note_id, Note.account_id == user.account_id)
    )
    if note is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "note not found")
    if note.user_id != user.id and user.role is not Role.OWNER:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "only the author or the owner can remove a note"
        )
    await session.delete(note)
    await session.commit()
