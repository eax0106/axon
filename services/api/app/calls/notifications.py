"""The notification bell: what the system wants the account to know."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select, update

from app.auth import CurrentUser
from app.db import Session
from app.models import Notification

router = APIRouter()


@router.get("/notifications")
async def list_notifications(
    user: CurrentUser,
    session: Session,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> dict[str, Any]:
    query = select(Notification).where(Notification.account_id == user.account_id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    rows = await session.scalars(
        query.order_by(Notification.created_at.desc(), Notification.id).limit(limit)
    )
    unread = await session.scalar(
        select(func.count()).where(
            Notification.account_id == user.account_id, Notification.read_at.is_(None)
        )
    )
    return {
        "unread_count": unread or 0,
        "items": [
            {
                "id": n.id,
                "kind": n.kind,
                "title": n.title,
                "body": n.body,
                "created_at": n.created_at,
                "read": n.read_at is not None,
            }
            for n in rows
        ],
    }


@router.post("/notifications/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def read_all(user: CurrentUser, session: Session) -> None:
    await session.execute(
        update(Notification)
        .where(Notification.account_id == user.account_id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    await session.commit()


@router.post("/notifications/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def read_one(notification_id: uuid.UUID, user: CurrentUser, session: Session) -> None:
    found = await session.scalar(
        select(Notification).where(
            Notification.id == notification_id, Notification.account_id == user.account_id
        )
    )
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "notification not found")
    found.read_at = found.read_at or datetime.now(UTC)
    await session.commit()
