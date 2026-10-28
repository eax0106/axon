"""What the customer sees of billing: the wallet, top-ups, statements, usage, invoices, settings."""

import json
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import func, select

from app.auth import CurrentUser, not_impersonating, refuse_in_support_session
from app.billing import invoices, ledger, payments
from app.billing.config import (
    ai_use_fee,
    extra_channel_monthly_fee,
    free_signup_credits,
    low_balance_threshold,
    number_monthly_fee,
    rate_per_minute,
    topup_limits,
)
from app.db import Session
from app.employees.router import OwnerUser
from app.models import (
    Account,
    Call,
    Employee,
    Invoice,
    Payment,
    VoiceTier,
    WalletEntry,
)
from app.providers.base import PaymentProvider, ProviderKind
from app.providers.registry import require

router = APIRouter()
IST = timedelta(hours=5, minutes=30)
GSTIN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PAID_EVENTS = ("payment.captured", "order.paid")


def _payments() -> PaymentProvider:
    provider = require(ProviderKind.PAYMENTS)
    assert isinstance(provider, PaymentProvider)
    return provider


async def _account(session: Session, user: CurrentUser) -> Account:
    account = await session.get(Account, user.account_id)
    assert account is not None  # FK guarantees it
    return account


def _cap(account: Account) -> str | None:
    cap = account.spend_cap_per_hour
    return None if cap is None else str(ledger.credits(cap))


@router.get("/wallet")
async def wallet(user: CurrentUser, session: Session) -> dict[str, Any]:
    account = await _account(session, user)
    threshold = low_balance_threshold()
    return {
        "balance": str(account.credit_balance),
        "spend_cap_per_hour": _cap(account),
        "low_balance_threshold": str(threshold),
        "low": account.credit_balance < threshold,  # the warning on the credit chip
    }


@router.get("/billing/rates")
async def rates(user: CurrentUser) -> dict[str, Any]:
    """What things cost, so the app shows the same numbers the ledger charges."""
    low, high = topup_limits()
    return {
        "per_minute": {tier.value: str(rate_per_minute(tier)) for tier in VoiceTier},
        "ai_use_fee": str(ai_use_fee()),
        "number_monthly_fee": str(number_monthly_fee()),
        "extra_channel_monthly_fee": str(extra_channel_monthly_fee()),
        "free_signup_credits": str(free_signup_credits()),
        "topup": {"min": str(low), "max": str(high), "presets": ["500", "1000", "2500", "5000"]},
    }


# --- Top-ups -----------------------------------------------------------------------------------


class OrderRequest(BaseModel):
    amount_inr: Annotated[Decimal, Field(max_digits=9, decimal_places=2)]


@router.post(
    "/wallet/topup/order",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(not_impersonating)],
)
async def topup_order(body: OrderRequest, user: OwnerUser, session: Session) -> dict[str, Any]:
    low, high = topup_limits()
    if not low <= body.amount_inr <= high:
        raise HTTPException(422, f"a top-up is between {low} and {high} rupees")
    provider = _payments()
    order = await provider.create_order(payments.paise(body.amount_inr), invoices.new_receipt())
    session.add(
        Payment(
            account_id=user.account_id,
            provider=provider.name,
            provider_order_id=order.id,
            amount_inr=body.amount_inr,
        )
    )
    await session.commit()
    return {
        "order_id": order.id,
        "key_id": provider.public_key(),
        "amount_paise": payments.paise(body.amount_inr),
        "currency": "INR",
    }


class Checkout(BaseModel):
    razorpay_order_id: str = Field(max_length=100)
    razorpay_payment_id: str = Field(max_length=100)
    razorpay_signature: str = Field(max_length=200)


@router.post("/wallet/topup/verify", dependencies=[Depends(not_impersonating)])
async def topup_verify(
    body: Checkout, user: OwnerUser, session: Session, response: Response
) -> dict[str, Any]:
    """The browser says the customer paid: believed only if the vendor signed it."""
    provider = _payments()
    mine = await session.scalar(
        select(Payment.id).where(
            Payment.provider_order_id == body.razorpay_order_id,
            Payment.account_id == user.account_id,
        )
    )
    if mine is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "order not found")
    if not provider.checkout_is_authentic(
        body.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "the payment signature is not valid")
    # The signature proves the checkout belongs to this order, not that the money was taken (with
    # manual capture a payment can stay authorized and be refunded): ask the vendor.
    info = await provider.fetch_payment(body.razorpay_payment_id)
    if info.order_id != body.razorpay_order_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "that payment is for another order")
    if not info.captured:
        response.status_code = status.HTTP_202_ACCEPTED  # the webhook credits it once captured
        return {"status": "pending", "balance": str(await ledger.balance(session, user.account_id))}
    payment = await payments.settle(
        session, body.razorpay_order_id, body.razorpay_payment_id, paid_paise=info.amount_paise
    )
    await session.commit()
    if payment is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "the amount paid is not the amount ordered"
        )
    return {
        "status": payment.status.value,
        "balance": str(await ledger.balance(session, user.account_id)),
    }


@router.post("/webhooks/razorpay")
async def razorpay_webhook(request: Request, session: Session) -> dict[str, str]:
    """The vendor says a payment went through (also when the browser never came back)."""
    provider = _payments()
    raw = await request.body()
    if not provider.webhook_is_authentic(raw, request.headers):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "the webhook signature is not valid")
    try:
        event = json.loads(raw)
        if event["event"] in PAID_EVENTS:
            paid = event["payload"]["payment"]["entity"]
            await payments.settle(
                session, str(paid["order_id"]), str(paid["id"]), paid_paise=int(paid["amount"])
            )
            await session.commit()
    except (KeyError, TypeError, ValueError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unreadable webhook") from None
    return {"status": "ok"}


# --- Transactions, statements, usage -----------------------------------------------------------


def _entry(entry: WalletEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "at": entry.created_at,
        "kind": entry.kind,
        "amount": str(entry.amount),
        "balance_after": str(entry.balance_after),  # the running balance
        "note": entry.note,
    }


@router.get("/billing/transactions")
async def transactions(
    user: CurrentUser,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: int | None = None,
) -> dict[str, Any]:
    """Newest first; pass the last `id` as `before` for the next page."""
    query = select(WalletEntry).where(WalletEntry.account_id == user.account_id)
    if before is not None:
        query = query.where(WalletEntry.id < before)
    rows = list(await session.scalars(query.order_by(WalletEntry.id.desc()).limit(limit)))
    return {"items": [_entry(e) for e in rows]}


def month_bounds(month: str) -> tuple[datetime, datetime]:
    """The Indian calendar month `YYYY-MM` as UTC instants."""
    try:
        first = date.fromisoformat(f"{month}-01")
    except ValueError:
        raise HTTPException(422, "month looks like 2026-11") from None
    after = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    start = datetime(first.year, first.month, 1, tzinfo=UTC) - IST
    return start, datetime(after.year, after.month, 1, tzinfo=UTC) - IST


def _this_month(now: datetime) -> str:
    return (now + IST).strftime("%Y-%m")


def _resolve_month(month: str, now: datetime) -> str:
    """`this`, `last` or `YYYY-MM`."""
    if month == "this":
        return _this_month(now)
    if month == "last":
        first = (now + IST).date().replace(day=1) - timedelta(days=1)
        return first.strftime("%Y-%m")
    return month


Month = Annotated[str, Query(pattern=r"^(this|last|\d{4}-\d{2})$")]


@router.get("/billing/statement")
async def statement(user: CurrentUser, session: Session, month: Month = "this") -> dict[str, Any]:
    """Opening balance, what came in and went out by kind, closing balance."""
    label = _resolve_month(month, datetime.now(UTC))
    start, end = month_bounds(label)
    account_id = user.account_id

    async def balance_at(moment: datetime) -> Decimal:
        value = await session.scalar(
            select(WalletEntry.balance_after)
            .where(WalletEntry.account_id == account_id, WalletEntry.created_at < moment)
            .order_by(WalletEntry.id.desc())
            .limit(1)
        )
        return value if value is not None else Decimal(0)

    totals = await session.execute(
        select(WalletEntry.kind, func.sum(WalletEntry.amount), func.count())
        .where(
            WalletEntry.account_id == account_id,
            WalletEntry.created_at >= start,
            WalletEntry.created_at < end,
        )
        .group_by(WalletEntry.kind)
    )
    by_kind = {kind.value: {"total": str(total), "entries": count} for kind, total, count in totals}
    return {
        "month": label,
        "opening_balance": str(await balance_at(start)),
        "by_kind": by_kind,
        "closing_balance": str(await balance_at(end)),
    }


@router.get("/billing/usage")
async def usage(user: CurrentUser, session: Session, month: Month = "this") -> dict[str, Any]:
    """What each employee's calls cost this month (billed calls only)."""
    start, end = month_bounds(_resolve_month(month, datetime.now(UTC)))
    rows = await session.execute(
        select(
            Call.employee_id,
            Employee.name,
            func.count(),
            func.coalesce(func.sum(Call.billed_seconds), 0),
            func.coalesce(func.sum(Call.credits_charged), 0),
        )
        .outerjoin(Employee, Employee.id == Call.employee_id)
        .where(
            Call.account_id == user.account_id,
            Call.billing_status == "billed",
            Call.ended_at >= start,
            Call.ended_at < end,
        )
        .group_by(Call.employee_id, Employee.name)
        .order_by(func.sum(Call.credits_charged).desc())
    )
    return {
        "employees": [
            {
                "employee_id": employee_id,
                "name": name,
                "calls": calls,
                "talk_seconds": int(seconds or 0),
                "credits": str(credits),
            }
            for employee_id, name, calls, seconds, credits in rows
        ]
    }


# --- Invoices ----------------------------------------------------------------------------------


def _invoice(invoice: Invoice) -> dict[str, Any]:
    return {
        "id": invoice.id,
        "number": invoice.number,
        "issued_at": invoice.issued_at,
        "total": str(invoice.total),
        "taxable": str(invoice.taxable),
        "cgst": str(invoice.cgst),
        "sgst": str(invoice.sgst),
        "igst": str(invoice.igst),
        **invoice.details,
    }


@router.get("/billing/invoices")
async def list_invoices(user: CurrentUser, session: Session) -> list[dict[str, Any]]:
    rows = await session.scalars(
        select(Invoice)
        .where(Invoice.account_id == user.account_id)
        .order_by(Invoice.issued_at.desc())
    )
    return [_invoice(i) for i in rows]


@router.get("/billing/invoices/{invoice_id}")
async def get_invoice(invoice_id: uuid.UUID, user: CurrentUser, session: Session) -> dict[str, Any]:
    invoice = await session.scalar(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.account_id == user.account_id)
    )
    if invoice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "invoice not found")
    return _invoice(invoice)


# --- Settings ----------------------------------------------------------------------------------


@router.get("/billing/settings")
async def get_settings(user: CurrentUser, session: Session) -> dict[str, Any]:
    account = await _account(session, user)
    return {"details": account.billing, "spend_cap_per_hour": _cap(account)}


class BillingSettings(BaseModel):
    legal_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = (
        None
    )
    gstin: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True)] | None = None
    address: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    state_code: Annotated[str, StringConstraints(pattern=r"^\d{2}$")] | None = None
    spend_cap_per_hour: Annotated[Decimal, Field(ge=0, max_digits=12, decimal_places=2)] | None = (
        None
    )


@router.put("/billing/settings")
async def put_settings(
    body: BillingSettings, request: Request, user: OwnerUser, session: Session
) -> dict[str, Any]:
    """Invoice details and the hourly spend cap. Only what is sent changes; `null` for the cap
    removes it. A support session may fix the invoice details but not the cap."""
    account = await _account(session, user)
    sent = body.model_fields_set
    details = dict(account.billing or {})
    for key in ("legal_name", "gstin", "address", "state_code"):
        if key in sent:
            value = getattr(body, key)
            if value:
                details[key] = value
            else:
                details.pop(key, None)
    gstin = details.get("gstin")
    if gstin and not GSTIN.match(gstin):
        raise HTTPException(422, "that GSTIN is not valid")
    if gstin and details.get("state_code") and gstin[:2] != details["state_code"]:
        raise HTTPException(422, "the GSTIN starts with the state code, and they differ")
    account.billing = details
    if "spend_cap_per_hour" in sent and body.spend_cap_per_hour != account.spend_cap_per_hour:
        refuse_in_support_session(request)
        account.spend_cap_per_hour = body.spend_cap_per_hour
    await session.commit()
    return await get_settings(user, session)
