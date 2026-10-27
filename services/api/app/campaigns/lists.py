"""Saved contact lists: upload once, start many campaigns from them."""

import uuid
from collections.abc import Sequence
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.campaigns import importer
from app.campaigns.contacts import chunks
from app.db import Session
from app.models import ContactList, ContactListItem, User

router = APIRouter(prefix="/contact-lists")


async def save_list(
    session: AsyncSession, user: User, name: str, rows: Sequence[importer.Row]
) -> ContactList:
    """Make the list, or add to the one of that name. Does not commit."""
    found = await session.scalar(
        select(ContactList).where(
            ContactList.account_id == user.account_id, ContactList.name == name
        )
    )
    if found is None:
        found = ContactList(account_id=user.account_id, name=name)
        session.add(found)
        await session.flush()
    for part in chunks(list(rows)):
        await session.execute(
            insert(ContactListItem)
            .values(
                [
                    {
                        "list_id": found.id,
                        "phone": r.phone,
                        "name": r.name,
                        "variables": r.variables,
                    }
                    for r in part
                ]
            )
            .on_conflict_do_nothing(index_elements=["list_id", "phone"])
        )
    return found


async def load_list(session: AsyncSession, user: User, list_id: uuid.UUID) -> ContactList:
    found = await session.scalar(
        select(ContactList).where(
            ContactList.id == list_id, ContactList.account_id == user.account_id
        )
    )
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "contact list not found")
    return found


class ListBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    text: str = Field(max_length=importer.MAX_TEXT)
    mapping: importer.Mapping


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(body: ListBody, user: CurrentUser, session: Session) -> dict[str, Any]:
    """Save a CSV as a list. Every column the mapping names is kept as a variable; a campaign
    later takes the ones its script declares."""
    try:
        parsed = importer.parse_csv(body.text, body.mapping, None)
    except importer.MappingError as exc:
        raise HTTPException(422, str(exc)) from exc
    saved = await save_list(session, user, body.name, parsed.rows)
    await session.commit()
    return {
        "id": saved.id,
        "name": saved.name,
        "added": len(parsed.rows),
        "duplicates_in_file": parsed.duplicates,
        "invalid_count": len(parsed.invalid),
        "invalid": [
            {"row": r.row, "value": r.value, "reason": r.reason} for r in parsed.invalid[:200]
        ],
    }


@router.get("")
async def lists(user: CurrentUser, session: Session) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(ContactList, func.count(ContactListItem.id))
        .join(ContactListItem, ContactListItem.list_id == ContactList.id, isouter=True)
        .where(ContactList.account_id == user.account_id)
        .group_by(ContactList.id)
        .order_by(ContactList.created_at.desc())
    )
    return [
        {"id": lst.id, "name": lst.name, "contacts": n, "created_at": lst.created_at}
        for lst, n in rows.all()
    ]


@router.get("/{list_id}")
async def get_list(
    list_id: uuid.UUID,
    user: CurrentUser,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    saved = await load_list(session, user, list_id)
    items = await session.scalars(
        select(ContactListItem)
        .where(ContactListItem.list_id == saved.id)
        .order_by(ContactListItem.phone)
        .limit(limit)
        .offset(offset)
    )
    total = await session.scalar(select(func.count()).where(ContactListItem.list_id == saved.id))
    return {
        "id": saved.id,
        "name": saved.name,
        "total": total,
        "contacts": [{"phone": i.phone, "name": i.name, "variables": i.variables} for i in items],
    }


@router.delete("/{list_id}")
async def remove(list_id: uuid.UUID, user: CurrentUser, session: Session) -> dict[str, bool]:
    """Delete the list. Campaigns made from it keep their contacts."""
    saved = await load_list(session, user, list_id)
    await session.execute(delete(ContactList).where(ContactList.id == saved.id))
    await session.commit()
    return {"deleted": True}
