"""Admin console: the accounts, a support session as an account's owner, and credit adjustments.

Every admin route is for platform staff only (`require_admin`), and a support session can never
reach one. What staff change is written to the audit log under their own id."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import IMPERSONATION_TTL, issue_token, require_admin
from app.billing import ledger
from app.db import Session
from app.models import (
    Account,
    AuditEntry,
    Call,
    Employee,
    LedgerKind,
    NumberStatus,
    PhoneNumber,
    Role,
    User,
    WalletEntry,
)

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
Staff = Annotated[User, Depends(require_admin)]
RECENT = timedelta(days=30)


class AccountRow(BaseModel):
    id: uuid.UUID
    name: str
    business_name: str | None
    owner_email: str | None
    credit_balance: Decimal
    created_at: datetime


def audit(
    session: AsyncSession, staff: User, account_id: uuid.UUID | None, action: str, **data: Any
) -> None:
    session.add(
        AuditEntry(
            account_id=account_id,
            actor_user_id=staff.id,
            action=action,
            target_type="account",
            target_id=str(account_id) if account_id else None,
            data=data,
        )
    )


async def _owner(session: AsyncSession, account_id: uuid.UUID) -> User | None:
    return await session.scalar(
        select(User)
        .where(User.account_id == account_id, User.role == Role.OWNER)
        .order_by(User.created_at)
        .limit(1)
    )


async def _account(session: AsyncSession, account_id: uuid.UUID) -> Account:
    account = await session.get(Account, account_id)
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "account not found")
    return account


@router.get("/accounts")
async def list_accounts(
    session: Session,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    """Every account, newest first; `q` finds an account by its name, business name or the email
    of one of its people."""
    owner = (
        select(User.email)
        .where(User.account_id == Account.id, User.role == Role.OWNER)
        .order_by(User.created_at)
        .limit(1)
        .scalar_subquery()
    )
    query = select(Account, owner)
    if q:
        like = f"%{q.strip()}%"
        people = select(User.account_id).where(User.email.ilike(like, escape="\\"))
        query = query.where(
            or_(
                Account.name.ilike(like),
                Account.business_name.ilike(like),
                Account.id.in_(people),
            )
        )
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.execute(
        query.order_by(Account.created_at.desc(), Account.id).limit(limit).offset(offset)
    )
    items = [
        AccountRow(
            id=a.id,
            name=a.name,
            business_name=a.business_name,
            owner_email=email,
            credit_balance=a.credit_balance,
            created_at=a.created_at,
        )
        for a, email in rows
    ]
    return {"total": total or 0, "limit": limit, "offset": offset, "items": items}


@router.get("/accounts/{account_id}")
async def account_detail(account_id: uuid.UUID, session: Session) -> dict[str, Any]:
    account = await _account(session, account_id)
    people = await session.scalars(
        select(User).where(User.account_id == account_id).order_by(User.created_at)
    )
    since = datetime.now(UTC) - RECENT

    async def count(*where: Any) -> int:
        return int(await session.scalar(select(func.count()).where(*where)) or 0)

    ledger_rows = await session.scalars(
        select(WalletEntry)
        .where(WalletEntry.account_id == account_id)
        .order_by(WalletEntry.id.desc())
        .limit(20)
    )
    return {
        "id": account.id,
        "name": account.name,
        "business_name": account.business_name,
        "credit_balance": account.credit_balance,
        "max_call_s": account.max_call_s,
        "created_at": account.created_at,
        "users": [{"id": u.id, "email": u.email, "role": u.role.value} for u in people],
        "employees": await count(Employee.account_id == account_id),
        "numbers": await count(
            PhoneNumber.account_id == account_id, PhoneNumber.status != NumberStatus.RELEASED
        ),
        "calls_30d": await count(Call.account_id == account_id, Call.created_at >= since),
        "ledger": [
            {
                "kind": e.kind.value,
                "amount": e.amount,
                "balance_after": e.balance_after,
                "note": e.note,
                "created_at": e.created_at,
            }
            for e in ledger_rows
        ],
    }


class Impersonate(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


@router.post("/accounts/{account_id}/impersonate")
async def impersonate(
    account_id: uuid.UUID, body: Impersonate, staff: Staff, session: Session
) -> dict[str, Any]:
    """A 30-minute session as the account's owner, to see what they see. The reason is logged,
    and so is every change made in the session (see `app.auth.current_user`)."""
    await _account(session, account_id)
    owner = await _owner(session, account_id)
    if owner is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "the account has no owner to act as")
    audit(
        session, staff, account_id, "impersonation_started", reason=body.reason, user=str(owner.id)
    )
    await session.commit()
    return {
        "access_token": issue_token(owner, impersonator=staff),
        "token_type": "bearer",
        "expires_in": int(IMPERSONATION_TTL.total_seconds()),
    }


class Adjustment(BaseModel):
    amount: Decimal = Field(max_digits=12, decimal_places=2)
    note: str = Field(min_length=3, max_length=300)


@router.post("/accounts/{account_id}/credits")
async def adjust_credits(
    account_id: uuid.UUID, body: Adjustment, staff: Staff, session: Session
) -> dict[str, Any]:
    """Add credits (a goodwill credit, say) or take them back. A take-back cannot leave the
    balance under zero (the ledger refuses it: 402)."""
    await _account(session, account_id)
    if body.amount == 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "the amount cannot be zero")
    posted = await ledger.post(
        session, account_id, LedgerKind.ADJUSTMENT, body.amount,
        ref_type="admin_adjustment", ref_id=uuid.uuid4().hex, note=body.note,
    )  # fmt: skip
    audit(session, staff, account_id, "credits_adjusted", amount=str(body.amount), note=body.note)
    await session.commit()
    return {"balance": posted.entry.balance_after}
