"""Leads across channels (one per phone number per account): table, board, notes, export."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, or_, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.calls.conversations import NoteIn, NoteOut, note_out
from app.calls.csvsafe import to_csv
from app.db import Session
from app.models import Call, Lead, Note, User

router = APIRouter()
EXPORT_LIMIT = 10_000
BOARD_PER_COLUMN = 50
NO_OUTCOME = "no_outcome"
# Columns an export can carry besides the lead's own fields ("field:<name>").
BASE_FIELDS = (
    "phone",
    "name",
    "created_at",
    "calls",
    "last_call_at",
    "last_outcome",
    "summary",
    "memory",
)


def _latest_call() -> Any:
    """Each lead's most recent real call."""
    return (
        select(Call.lead_id, Call.outcome, Call.created_at, Call.summary)
        .where(Call.is_test.is_(False), Call.lead_id.is_not(None))
        .ext(distinct_on(Call.lead_id))
        .order_by(Call.lead_id, Call.created_at.desc())
        .subquery()
    )


def _call_counts() -> Any:
    return (
        select(Call.lead_id, func.count().label("n"))
        .where(Call.is_test.is_(False), Call.lead_id.is_not(None))
        .group_by(Call.lead_id)
        .subquery()
    )


def _base(
    account_id: uuid.UUID, q: str | None, outcome: str | None, employee_id: uuid.UUID | None
) -> tuple[Select[Any], Any, Any]:
    last, counts = _latest_call(), _call_counts()
    query: Any = (
        select(
            Lead, last.c.outcome, last.c.created_at, last.c.summary, func.coalesce(counts.c.n, 0)
        )
        .join(last, last.c.lead_id == Lead.id, isouter=True)
        .join(counts, counts.c.lead_id == Lead.id, isouter=True)
        .where(Lead.account_id == account_id)
    )
    if q:
        like = f"%{q.strip()}%"
        query = query.where(or_(Lead.phone.ilike(like), Lead.name.ilike(like)))
    if outcome == NO_OUTCOME:
        query = query.where(last.c.outcome.is_(None))
    elif outcome:
        query = query.where(last.c.outcome == outcome)
    if employee_id:
        query = query.where(
            Lead.id.in_(
                select(Call.lead_id).where(Call.employee_id == employee_id, Call.is_test.is_(False))
            )
        )
    return query, last, counts


class LeadRow(BaseModel):
    id: uuid.UUID
    phone: str
    name: str | None
    created_at: datetime
    last_outcome: str | None
    last_call_at: datetime | None
    calls: int
    fields: dict[str, Any]


def _row(
    lead: Lead, outcome: str | None, last_at: datetime | None, _summary: str | None, calls: int
) -> LeadRow:
    return LeadRow(
        id=lead.id,
        phone=lead.phone,
        name=lead.name,
        created_at=lead.created_at,
        last_outcome=outcome,
        last_call_at=last_at,
        calls=int(calls),
        fields=lead.fields,
    )


@router.get("/leads")
async def list_leads(
    user: CurrentUser,
    session: Session,
    q: Annotated[str | None, Query(max_length=100)] = None,
    outcome: str | None = None,
    employee_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    query, _, _ = _base(user.account_id, q, outcome, employee_id)
    total = await session.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    rows = (
        await session.execute(query.order_by(Lead.created_at.desc()).limit(limit).offset(offset))
    ).all()
    return {
        "total": total or 0,
        "limit": limit,
        "offset": offset,
        "items": [_row(*r) for r in rows],
    }


@router.get("/leads/board")
async def board(
    user: CurrentUser,
    session: Session,
    q: Annotated[str | None, Query(max_length=100)] = None,
    employee_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Leads grouped by the outcome of their latest call (a kanban: one column per outcome)."""
    query, last, _ = _base(user.account_id, q, None, employee_id)
    rows = (await session.execute(query.order_by(last.c.created_at.desc().nulls_last()))).all()
    columns: dict[str, list[LeadRow]] = {}
    counts: dict[str, int] = {}
    for r in rows:
        key = r[1] or NO_OUTCOME
        counts[key] = counts.get(key, 0) + 1
        if len(columns.setdefault(key, [])) < BOARD_PER_COLUMN:
            columns[key].append(_row(*r))
    return {"columns": columns, "counts": counts}


@router.get("/leads/export.csv")
async def export_leads(
    user: CurrentUser,
    session: Session,
    fields: Annotated[str, Query(max_length=500)] = "phone,name,last_outcome,calls",
    q: Annotated[str | None, Query(max_length=100)] = None,
    outcome: str | None = None,
) -> Response:
    """CSV of leads with only the columns asked for: base columns and `field:<name>` lead fields."""
    chosen = [f.strip() for f in fields.split(",") if f.strip()]
    bad = [f for f in chosen if f not in BASE_FIELDS and not f.startswith("field:")]
    if not chosen or bad:
        raise HTTPException(
            422, f"unknown columns {bad}; choose from {', '.join(BASE_FIELDS)} or field:<name>"
        )
    query, _, _ = _base(user.account_id, q, outcome, None)
    rows = (await session.execute(query.order_by(Lead.created_at.desc()).limit(EXPORT_LIMIT))).all()
    last_summary = {r[0].id: r[3] for r in rows}

    def value(
        lead: Lead, column: str, outcome_: str | None, last_at: datetime | None, calls: int
    ) -> Any:
        if column.startswith("field:"):
            return lead.fields.get(column.removeprefix("field:"))
        return {
            "phone": lead.phone,
            "name": lead.name,
            "created_at": lead.created_at.isoformat(),
            "calls": calls,
            "last_call_at": last_at.isoformat() if last_at else None,
            "last_outcome": outcome_,
            "summary": last_summary[lead.id],
            "memory": lead.memory,
        }[column]

    body = to_csv(chosen, ([value(r[0], c, r[1], r[2], r[4]) for c in chosen] for r in rows))
    return Response(
        body,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )


async def own_lead(session: AsyncSession, user: User, lead_id: uuid.UUID) -> Lead:
    lead = await session.scalar(
        select(Lead).where(Lead.id == lead_id, Lead.account_id == user.account_id)
    )
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "lead not found")
    return lead


@router.get("/leads/{lead_id}")
async def lead_detail(lead_id: uuid.UUID, user: CurrentUser, session: Session) -> dict[str, Any]:
    lead = await own_lead(session, user, lead_id)
    calls = await session.scalars(
        select(Call)
        .where(Call.lead_id == lead.id, Call.is_test.is_(False))
        .order_by(Call.created_at.desc())
        .limit(100)
    )
    notes = await session.scalars(
        select(Note).where(Note.lead_id == lead.id).order_by(Note.created_at.desc())
    )
    return {
        "id": lead.id,
        "phone": lead.phone,
        "name": lead.name,
        "fields": lead.fields,
        "memory": lead.memory,
        "created_at": lead.created_at,
        "calls": [
            {
                "id": c.id,
                "created_at": c.created_at,
                "channel": c.channel.value,
                "status": c.status.value,
                "outcome": c.outcome,
                "sentiment": c.sentiment,
                "summary": c.summary,
                "attempt": c.attempt,
            }
            for c in calls
        ],
        "notes": [note_out(n).model_dump() for n in notes],
    }


class LeadPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)


@router.patch("/leads/{lead_id}")
async def rename_lead(
    lead_id: uuid.UUID, body: LeadPatch, user: CurrentUser, session: Session
) -> dict[str, Any]:
    lead = await own_lead(session, user, lead_id)
    lead.name = (body.name or "").strip() or None
    await session.commit()
    return {"id": lead.id, "name": lead.name}


@router.get("/leads/{lead_id}/notes")
async def lead_notes(lead_id: uuid.UUID, user: CurrentUser, session: Session) -> list[NoteOut]:
    lead = await own_lead(session, user, lead_id)
    rows = await session.scalars(
        select(Note).where(Note.lead_id == lead.id).order_by(Note.created_at.desc())
    )
    return [note_out(n) for n in rows]


@router.post("/leads/{lead_id}/notes", status_code=status.HTTP_201_CREATED)
async def add_lead_note(
    lead_id: uuid.UUID, body: NoteIn, user: CurrentUser, session: Session
) -> NoteOut:
    lead = await own_lead(session, user, lead_id)
    note = Note(
        account_id=user.account_id, lead_id=lead.id, user_id=user.id, body=body.body.strip()
    )
    session.add(note)
    await session.commit()
    return note_out(note)


@router.delete("/leads/{lead_id}/memory", status_code=status.HTTP_204_NO_CONTENT)
async def reset_lead_memory(lead_id: uuid.UUID, user: CurrentUser, session: Session) -> None:
    """Forget what earlier calls taught us about this person."""
    lead = await own_lead(session, user, lead_id)
    lead.memory = None
    await session.commit()
