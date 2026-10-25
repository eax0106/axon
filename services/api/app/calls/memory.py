"""Caller memory: whether the account remembers callers across calls, and forgetting them."""

from fastapi import APIRouter, status
from pydantic import BaseModel
from sqlalchemy import update

from app.auth import CurrentUser
from app.db import Session
from app.employees.router import OwnerUser
from app.models import Account, Lead

router = APIRouter()


class MemorySetting(BaseModel):
    enabled: bool


@router.get("/account/caller-memory")
async def get_setting(user: CurrentUser, session: Session) -> MemorySetting:
    account = await session.get(Account, user.account_id)
    assert account is not None  # FK guarantees it
    return MemorySetting(enabled=account.caller_memory)


@router.put("/account/caller-memory")
async def set_setting(body: MemorySetting, user: OwnerUser, session: Session) -> MemorySetting:
    """Turning it off stops new memories and stops using old ones; it keeps what was stored (reset
    deletes it)."""
    account = await session.get(Account, user.account_id)
    assert account is not None  # FK guarantees it
    account.caller_memory = body.enabled
    await session.commit()
    return body


@router.delete("/account/caller-memory/data", status_code=status.HTTP_204_NO_CONTENT)
async def forget_everyone(user: OwnerUser, session: Session) -> None:
    await session.execute(
        update(Lead).where(Lead.account_id == user.account_id).values(memory=None)
    )
    await session.commit()
