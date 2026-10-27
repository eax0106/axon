"""Credit top-ups through the payment provider.

The browser and the provider's webhook both report the same payment, in either order, and both
call `settle`: the payment row is locked, so the wallet is credited exactly once and the invoice
issued exactly once.
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import invoices, ledger
from app.models import LedgerKind, Payment, PaymentStatus
from app.numbers import renewals

log = logging.getLogger("axon.billing")
PAISE_PER_RUPEE = 100


def paise(amount_inr: Decimal) -> int:
    return int(amount_inr * PAISE_PER_RUPEE)


async def settle(
    session: AsyncSession,
    order_id: str,
    payment_id: str,
    *,
    paid_paise: int | None = None,
    now: datetime | None = None,
) -> Payment | None:
    """Credit the wallet for the order's payment. Returns the payment (already settled counts),
    or None for an order we never opened or a paid amount that is not the amount ordered, which
    credits nothing. Does not commit."""
    payment = await session.scalar(
        select(Payment).where(Payment.provider_order_id == order_id).with_for_update()
    )
    if payment is None:
        log.warning("payment for unknown order %s ignored", order_id)
        return None
    if paid_paise is not None and paid_paise != paise(payment.amount_inr):
        log.warning(
            "payment %s paid %s paise for order %s: not credited", payment_id, paid_paise, order_id
        )
        return None
    if payment.status is PaymentStatus.PAID:
        return payment
    now = now or datetime.now(UTC)
    payment.status = PaymentStatus.PAID
    payment.provider_payment_id = payment_id
    await ledger.post(
        session,
        payment.account_id,
        LedgerKind.TOPUP,
        payment.amount_inr,
        ref_type="payment",
        ref_id=str(payment.id),
        note=f"top-up {payment.amount_inr:.2f}",
    )
    await invoices.issue(session, payment, now)
    await renewals.recover(session, payment.account_id, renewals.today_ist(now))  # rent waiting
    return payment
