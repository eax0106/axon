"""The daily email: how yesterday's incoming calls went (India time), once per account."""

import logging
from collections import Counter
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.billing.alerts import email_owner
from app.inbound.settings import of as inbound_of
from app.instant.rules import IST, local
from app.models import (
    Account,
    Call,
    CallEvent,
    DailySummary,
    Direction,
    Employee,
    InboundMessage,
)
from app.providers.base import ProviderKind, ProviderNotConfiguredError
from app.providers.registry import require

log = logging.getLogger("axon.inbound")
SEND_FROM_HOUR = 8  # India time: yesterday is over and the owner is about to start the day
MAX_LISTED = 10


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """The start and end (UTC) of an India-time calendar day."""
    start = datetime(day.year, day.month, day.day, tzinfo=UTC) - timedelta(minutes=IST)
    return start, start + timedelta(days=1)


async def send_due(factory: async_sessionmaker[AsyncSession], now: datetime) -> int:
    """From 8 AM India time, send yesterday's summary to every account that has not had it and had
    incoming calls. The day is claimed (a row) before the email goes, so a crash loses one email
    rather than sending two. Returns how many emails went out."""
    here = local(now, IST)
    if here.hour < SEND_FROM_HOUR:
        return 0
    try:
        require(ProviderKind.EMAIL)
    except ProviderNotConfiguredError:
        return 0  # nothing is claimed, so the summary goes out once an email provider exists
    yesterday = here.date() - timedelta(days=1)
    start, end = day_bounds(yesterday)
    async with factory() as session:
        accounts = list(
            await session.scalars(
                select(Call.account_id)
                .where(
                    Call.direction == Direction.INBOUND,
                    Call.is_test.is_(False),
                    Call.created_at >= start,
                    Call.created_at < end,
                )
                .group_by(Call.account_id)
            )
        )
    sent = 0
    for account_id in accounts:
        async with factory() as session:
            claimed = await session.execute(
                insert(DailySummary)
                .values(account_id=account_id, day=yesterday)
                .on_conflict_do_nothing()
                .returning(DailySummary.account_id)
            )
            if claimed.scalar() is None:
                continue  # already sent
            await session.commit()
            text = await compose(session, account_id, yesterday)
            if text is None:  # nobody wanted it, or nothing it covers: the day stays claimed
                continue
            subject, body = text
            await email_owner(session, account_id, subject, body)
            sent += 1
    return sent


async def compose(session: AsyncSession, account_id: object, day: date) -> tuple[str, str] | None:
    """(subject, text) for the account's day, or None if no employee has the summary on or there
    was nothing to report."""
    start, end = day_bounds(day)
    employees = {
        e.id: e
        for e in await session.scalars(select(Employee).where(Employee.account_id == account_id))
        if inbound_of(e.inbound).daily_summary
    }
    calls = list(
        await session.scalars(
            select(Call).where(
                Call.account_id == account_id,
                Call.direction == Direction.INBOUND,
                Call.is_test.is_(False),
                Call.created_at >= start,
                Call.created_at < end,
                Call.employee_id.in_(list(employees)),
            )
        )
    )
    if not calls:
        return None
    answered = [c for c in calls if c.miss_reason is None]
    missed = [c for c in calls if c.miss_reason is not None]
    talk = sum(c.duration_s or 0 for c in answered)
    transfers = await session.scalar(
        select(func.count()).where(
            CallEvent.call_id.in_([c.id for c in answered]), CallEvent.type == "transferred"
        )
    )
    new_messages = list(
        await session.scalars(
            select(InboundMessage)
            .where(InboundMessage.call_id.in_([c.id for c in calls]))
            .order_by(InboundMessage.created_at)
        )
    )
    open_now = await session.scalar(
        select(func.count()).where(
            InboundMessage.account_id == account_id, InboundMessage.done_at.is_(None)
        )
    )
    account = await session.get(Account, account_id)
    business = (account.business_name or account.name) if account else "your business"
    lines = [
        f"Incoming calls for {business} on {day.strftime('%d %b %Y')} (India time)",
        "",
        f"Answered: {len(answered)}  -  Missed: {len(missed)}  -  "
        f"Talk time: {talk // 60} min {talk % 60} s  -  Handed to a person: {transfers or 0}",
    ]
    if missed:
        lines += ["", "Missed callers, by reason:"]
        lines += [f"  {n} x {why}" for why, n in Counter(c.miss_reason for c in missed).items()]
    if new_messages:
        lines += ["", f"Messages and call-back requests ({len(new_messages)}):"]
        for m in new_messages[:MAX_LISTED]:
            who = m.name or m.phone or "a caller"
            lines.append(f"  {who}: {m.body}")
        if len(new_messages) > MAX_LISTED:
            lines.append(f"  ... and {len(new_messages) - MAX_LISTED} more")
    lines += ["", f"Waiting for you: {open_now or 0} message(s) not yet ticked off."]
    subject = f"Yesterday's calls: {len(answered)} answered, {len(missed)} missed"
    return subject, "\n".join(lines)
