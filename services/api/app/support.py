"""Support: a chat thread between an account and ALTERX staff, feedback, and a 1-5 rating of a
call. Staff read everything in one inbox and answer a thread; the answer lands in that account's
thread and its notification bell."""

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.admin.accounts import Staff
from app.auth import CurrentUser, require_admin
from app.db import Session
from app.models import Account, Call, Notification, SupportMessage

router = APIRouter()
staff_router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
Kind = Literal["chat", "feedback", "rating"]


class MessageOut(BaseModel):
    id: uuid.UUID
    account_id: uuid.UUID
    kind: str
    from_staff: bool
    body: str
    rating: int | None
    call_id: uuid.UUID | None
    created_at: datetime


def _out(m: SupportMessage) -> MessageOut:
    return MessageOut(
        id=m.id,
        account_id=m.account_id,
        kind=m.kind,
        from_staff=m.from_staff,
        body=m.body,
        rating=m.rating,
        call_id=m.call_id,
        created_at=m.created_at,
    )


class Text(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class Rating(BaseModel):
    call_id: uuid.UUID
    rating: int = Field(ge=1, le=5)
    body: str = Field(default="", max_length=4000)


async def _save(session: Session, message: SupportMessage) -> MessageOut:
    session.add(message)
    await session.commit()
    return _out(message)


@router.get("/support/chat")
async def chat_thread(
    user: CurrentUser, session: Session, limit: Annotated[int, Query(ge=1, le=200)] = 100
) -> list[MessageOut]:
    """The account's chat with staff, oldest first (the latest `limit` messages)."""
    rows = await session.scalars(
        select(SupportMessage)
        .where(SupportMessage.account_id == user.account_id, SupportMessage.kind == "chat")
        .order_by(SupportMessage.created_at.desc(), SupportMessage.id)
        .limit(limit)
    )
    return [_out(m) for m in reversed(list(rows))]


@router.post("/support/chat", status_code=status.HTTP_201_CREATED)
async def write_chat(body: Text, user: CurrentUser, session: Session) -> MessageOut:
    return await _save(
        session,
        SupportMessage(account_id=user.account_id, user_id=user.id, kind="chat", body=body.body),
    )


@router.post("/support/feedback", status_code=status.HTTP_201_CREATED)
async def feedback(body: Text, user: CurrentUser, session: Session) -> MessageOut:
    return await _save(
        session,
        SupportMessage(
            account_id=user.account_id, user_id=user.id, kind="feedback", body=body.body
        ),
    )


@router.post("/support/rating", status_code=status.HTTP_201_CREATED)
async def rate_call(body: Rating, user: CurrentUser, session: Session) -> MessageOut:
    """Rate one of the account's own calls, 1 to 5, with an optional comment."""
    call = await session.get(Call, body.call_id)
    if call is None or call.account_id != user.account_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "call not found")
    return await _save(
        session,
        SupportMessage(
            account_id=user.account_id,
            user_id=user.id,
            kind="rating",
            body=body.body,
            rating=body.rating,
            call_id=call.id,
        ),
    )


@staff_router.get("/support")
async def inbox(
    session: Session,
    kind: Kind | None = None,
    account_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    """Every account's chat messages, feedback and ratings, newest first, with the account name."""
    query = select(SupportMessage, Account.name).join(
        Account, Account.id == SupportMessage.account_id
    )
    if kind is not None:
        query = query.where(SupportMessage.kind == kind)
    if account_id is not None:
        query = query.where(SupportMessage.account_id == account_id)
    rows = await session.execute(
        query.order_by(SupportMessage.created_at.desc(), SupportMessage.id)
        .limit(limit)
        .offset(offset)
    )
    return {
        "limit": limit,
        "offset": offset,
        "items": [{**_out(m).model_dump(), "account_name": name} for m, name in rows],
    }


@staff_router.post("/support/{account_id}/reply", status_code=status.HTTP_201_CREATED)
async def reply(account_id: uuid.UUID, body: Text, staff: Staff, session: Session) -> MessageOut:
    if await session.get(Account, account_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "account not found")
    session.add(
        Notification(
            account_id=account_id,
            kind="support_reply",
            title="Support replied",
            body=body.body[:300],
        )
    )
    return await _save(
        session,
        SupportMessage(
            account_id=account_id, user_id=staff.id, kind="chat", from_staff=True, body=body.body
        ),
    )
