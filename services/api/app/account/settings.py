"""The account's own settings: its name, the business name the AI introduces itself with, the
longest any of its calls may run (10 s to 60 min; every call is hung up at that point), and the
terms of service its owner has accepted."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth import CurrentUser, not_impersonating
from app.db import Session
from app.employees.router import OwnerUser
from app.models import Account, AuditEntry

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


class Terms(BaseModel):
    version: str | None
    accepted_at: datetime | None


class TermsAccept(BaseModel):
    version: str = Field(min_length=1, max_length=40)


@router.get("/terms")
async def read_terms(user: CurrentUser, session: Session) -> Terms:
    account = await session.get(Account, user.account_id)
    assert account is not None
    return Terms(version=account.terms_version, accepted_at=account.terms_accepted_at)


@router.post("/terms", dependencies=[Depends(not_impersonating)])
async def accept_terms(body: TermsAccept, user: OwnerUser, session: Session) -> Terms:
    """The owner accepts a version of the terms. Only the owner can, never staff in a support
    session; the audit log keeps who accepted which version and when."""
    account = await session.get(Account, user.account_id)
    assert account is not None
    account.terms_version, account.terms_accepted_at = body.version.strip(), datetime.now(UTC)
    session.add(
        AuditEntry(
            account_id=account.id,
            actor_user_id=user.id,
            action="terms_accepted",
            target_type="terms",
            target_id=account.terms_version,
        )
    )
    await session.commit()
    return Terms(version=account.terms_version, accepted_at=account.terms_accepted_at)
