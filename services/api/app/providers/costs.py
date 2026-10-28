"""What the vendors cost us: the usage every call metered (speech seconds, LLM tokens, characters
spoken, from the engine's `usage` event) and the carrier's billed seconds, priced at the rates
staff entered from each vendor's price list. Usage without a rate is shown with its cost left
empty, never guessed."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Numeric, cast, column, func, literal, select, union_all
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Subquery

from app.models import Call, CallEvent, PhoneNumber, ProviderRate
from app.numbers.renewals import IST

CARRIER_UNIT = "seconds"  # what a carrier's billed time is metered in


@dataclass(frozen=True)
class Usage:
    kind: str
    vendor: str
    unit: str
    amount: Decimal
    rate: Decimal | None  # INR per unit; None until staff enter one
    day: date | None = None  # the India date, when asked for per day

    @property
    def cost(self) -> Decimal | None:
        return None if self.rate is None else (self.amount * self.rate).quantize(Decimal("0.01"))


def _metered(since: datetime, until: datetime) -> Subquery:
    meters = func.jsonb_array_elements(CallEvent.data["meters"])
    meter = meters.table_valued(column("value", JSONB)).alias("m")
    value = meter.c.value
    engine = (
        select(
            value["kind"].astext.label("kind"),
            value["vendor"].astext.label("vendor"),
            value["unit"].astext.label("unit"),
            cast(value["amount"].astext, Numeric).label("amount"),
            CallEvent.at.label("at"),
        )
        .select_from(CallEvent)
        .join(meter, literal(True))
        .where(CallEvent.type == "usage", CallEvent.at >= since, CallEvent.at < until)
    )
    carrier = (
        select(
            literal("telephony").label("kind"),
            PhoneNumber.provider.label("vendor"),
            literal(CARRIER_UNIT).label("unit"),
            cast(Call.billed_seconds, Numeric).label("amount"),
            Call.ended_at.label("at"),
        )
        .join(PhoneNumber, PhoneNumber.id == Call.number_id)
        .where(Call.billed_seconds > 0, Call.ended_at >= since, Call.ended_at < until)
    )
    return union_all(engine, carrier).subquery()


async def usage(
    session: AsyncSession,
    since: datetime,
    until: datetime,
    *,
    vendor: str | None = None,
    per_day: bool = False,
) -> list[Usage]:
    """Usage and cost per (kind, vendor, unit) between `since` and `until`, per India day if
    `per_day`."""
    rows = _metered(since, until)
    day = func.date(func.timezone("UTC", rows.c.at) + IST).label("day")
    keys = [rows.c.kind, rows.c.vendor, rows.c.unit, *([day] if per_day else [])]
    query = (
        select(*keys, func.sum(rows.c.amount), ProviderRate.inr_per_unit)
        .outerjoin(
            ProviderRate,
            (ProviderRate.kind == rows.c.kind)
            & (ProviderRate.vendor == rows.c.vendor)
            & (ProviderRate.unit == rows.c.unit),
        )
        .group_by(*keys, ProviderRate.inr_per_unit)
        .order_by(*keys)
    )
    if vendor is not None:
        query = query.where(rows.c.vendor == vendor)
    result = await session.execute(query)
    return [
        Usage(r.kind, r.vendor, r.unit, r[-2], r[-1], r.day if per_day else None) for r in result
    ]


def total(rows: list[Usage]) -> Decimal:
    """The known cost of `rows` (usage without a rate adds nothing)."""
    return sum((r.cost for r in rows if r.cost is not None), Decimal("0"))
