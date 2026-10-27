"""GST invoices for credit top-ups.

The price of credits includes GST, so a payment of ₹P is P credits and an invoice whose taxable
value is P / (1 + rate). The rate, the service code and the seller are configuration
(app.billing.config); each invoice keeps the values it was issued with. Tax is CGST plus SGST when
the buyer is in the seller's state (or has given no state) and IGST otherwise. Numbers run without
gaps within a financial year (April to March, Indian time): PREFIX/2026-27/000001.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.config import gst_rate_percent, gst_sac_code, seller_details
from app.models import Account, Invoice, InvoiceCounter, Payment

IST = timedelta(hours=5, minutes=30)
PAISE = Decimal("0.01")


def financial_year(moment: datetime) -> str:
    """'2026-27' for any day from 1 April 2026 to 31 March 2027, by the Indian date."""
    local = moment.astimezone(UTC) + IST
    start = local.year if local.month >= 4 else local.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def split_tax(total: Decimal, rate_percent: Decimal, *, same_state: bool) -> dict[str, Decimal]:
    """Taxable value and tax out of a tax-inclusive `total`. The parts always add up to it."""
    taxable = (total / (1 + rate_percent / 100)).quantize(PAISE, rounding=ROUND_HALF_UP)
    tax = total - taxable
    zero = Decimal("0.00")
    if not same_state:
        return {"taxable": taxable, "cgst": zero, "sgst": zero, "igst": tax}
    cgst = (tax / 2).quantize(PAISE, rounding=ROUND_HALF_UP)
    return {"taxable": taxable, "cgst": cgst, "sgst": tax - cgst, "igst": zero}


async def _next_number(session: AsyncSession, fy: str) -> int:
    await session.execute(
        insert(InvoiceCounter).values(fy=fy, last=0).on_conflict_do_nothing(index_elements=["fy"])
    )
    counter = await session.scalar(
        select(InvoiceCounter).where(InvoiceCounter.fy == fy).with_for_update()
    )
    assert counter is not None  # inserted just above
    counter.last += 1
    return counter.last


async def issue(session: AsyncSession, payment: Payment, now: datetime) -> Invoice:
    """The invoice for a paid payment; asking again returns the same one."""
    existing = await session.scalar(select(Invoice).where(Invoice.payment_id == payment.id))
    if existing is not None:
        return existing
    account = await session.get(Account, payment.account_id)
    assert account is not None  # FK guarantees it
    seller = seller_details()
    buyer = dict(account.billing or {})
    buyer.setdefault("legal_name", account.business_name or account.name)
    buyer_state = str(buyer.get("state_code") or "")
    same_state = not buyer_state or buyer_state == seller["state_code"]
    rate = gst_rate_percent()
    parts = split_tax(payment.amount_inr, rate, same_state=same_state)
    fy = financial_year(now)
    number = f"{seller['invoice_prefix']}/{fy}/{await _next_number(session, fy):06d}"
    invoice = Invoice(
        account_id=payment.account_id,
        payment_id=payment.id,
        number=number,
        issued_at=now,
        total=payment.amount_inr,
        details={
            "seller": seller,
            "buyer": buyer,
            "gst_rate_percent": str(rate),
            "sac_code": gst_sac_code(),
            "place_of_supply": buyer_state or seller["state_code"],
            "description": f"{payment.amount_inr:.2f} credits (prepaid wallet top-up)",
            "provider_payment_id": payment.provider_payment_id,
        },
        **parts,
    )
    session.add(invoice)
    await session.flush()
    return invoice


def new_receipt() -> str:
    """Razorpay allows 40 characters."""
    return "axon_" + uuid.uuid4().hex[:32]
