"""The account's own settings: its name, the business name the AI introduces itself with, and the
longest any of its calls may run (10 s to 60 min; every call is hung up at that point)."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.auth import CurrentUser
from app.db import Session
from app.employees.router import OwnerUser
from app.models import Account

router = APIRouter(prefix="/account")


class AccountSettings(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    business_name: str | None = Field(default=None, max_length=200)
    max_call_s: int = Field(ge=10, le=3600)


def _out(account: Account) -> AccountSettings:
    return AccountSettings(
        name=account.name, business_name=account.business_name, max_call_s=account.max_call_s
    )


@router.get("/settings")
async def read_settings(user: CurrentUser, session: Session) -> AccountSettings:
    account = await session.get(Account, user.account_id)
    assert account is not None  # FK guarantees it
    return _out(account)


@router.put("/settings")
async def change_settings(
    body: AccountSettings, user: OwnerUser, session: Session
) -> AccountSettings:
    account = await session.get(Account, user.account_id)
    assert account is not None
    account.name, account.max_call_s = body.name.strip(), body.max_call_s
    account.business_name = (body.business_name or "").strip() or None
    await session.commit()
    return _out(account)
