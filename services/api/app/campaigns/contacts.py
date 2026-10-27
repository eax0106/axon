"""What happens to a campaign's contacts: adding them, skipping the ones that must not be called,
and moving each one on when a call to it ends.

A contact is `pending` (waiting for its time), `calling`, `callback` (asked to be called at a time),
`done` (answered), `exhausted` (tried as often as allowed, or an unknown outcome a person must look
at), `skipped` (a rule says never: do-not-call, exclusion list, another campaign called lately) or
`canceled` (a person stopped it). Every function takes `now` and does not commit.
"""

import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.campaigns import settings as campaign_settings
from app.campaigns.importer import Row
from app.instant import rules
from app.models import (
    Call,
    CallStatus,
    Campaign,
    CampaignContact,
    CampaignExclusion,
    CampaignStatus,
    ContactStatus,
    DncEntry,
    DncSource,
    Lead,
    Notification,
)

CHUNK = 2000  # rows per statement: far under the driver's bind-parameter limit
OPEN = (ContactStatus.PENDING, ContactStatus.CALLBACK, ContactStatus.CALLING)
EXCLUDED = "on this campaign's exclusion list"
DNC_REASONS = ("on the do-not-call list", "asked not to be called again")
UNKNOWN_OUTCOME = "nobody knows how the call went: check with the carrier before calling again"


def affected(result: object) -> int:
    """Rows an UPDATE changed."""
    return int(cast("CursorResult[Any]", result).rowcount or 0)


def chunks[T](items: Sequence[T], size: int = CHUNK) -> Iterator[Sequence[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


@dataclass
class Added:
    added: int = 0
    already_in_campaign: int = 0
    skipped_dnc: int = 0
    excluded: int = 0


async def dnc_reasons(
    session: AsyncSession, account_id: uuid.UUID, phones: Sequence[str], skip_dnc: bool
) -> dict[str, str]:
    """Which of these numbers must not be called, and why. A person who asked not to be called is
    never called, whatever the campaign's switch says; the switch covers the rest of the list."""
    out: dict[str, str] = {}
    for part in chunks(phones):
        rows = await session.execute(
            select(DncEntry.phone, DncEntry.source).where(
                DncEntry.account_id == account_id, DncEntry.phone.in_(part)
            )
        )
        for phone, source in rows:
            if source is DncSource.CALLER_REQUEST:
                out[phone] = "asked not to be called again"
            elif skip_dnc:
                out[phone] = "on the do-not-call list"
    return out


async def excluded_phones(
    session: AsyncSession, campaign_id: uuid.UUID, phones: Sequence[str]
) -> set[str]:
    found: set[str] = set()
    for part in chunks(phones):
        found.update(
            await session.scalars(
                select(CampaignExclusion.phone).where(
                    CampaignExclusion.campaign_id == campaign_id,
                    CampaignExclusion.phone.in_(part),
                )
            )
        )
    return found


async def add_rows(
    session: AsyncSession, campaign: Campaign, rows: Sequence[Row], now: datetime
) -> Added:
    """Add contacts. A number the rules forbid is still stored, as `skipped` with the reason, so
    the owner sees what became of every row. A number already in the campaign is left alone."""
    settings = campaign_settings.of(campaign.settings)
    phones = [r.phone for r in rows]
    dnc = await dnc_reasons(session, campaign.account_id, phones, settings.skip_dnc)
    excluded = await excluded_phones(session, campaign.id, phones)
    report = Added()
    for part in chunks(list(enumerate(rows))):
        values = []
        for index, row in part:
            status, reason = ContactStatus.PENDING, None
            if row.phone in excluded:
                status, reason = ContactStatus.SKIPPED, EXCLUDED
            elif row.phone in dnc:
                status, reason = ContactStatus.SKIPPED, dnc[row.phone]
            values.append(
                {
                    "campaign_id": campaign.id,
                    "phone": row.phone,
                    "name": row.name,
                    "variables": row.variables,
                    "status": status,
                    "reason": reason,
                    "created_at": now + timedelta(microseconds=index),  # keeps the upload order
                }
            )
        stored = await session.execute(
            insert(CampaignContact)
            .values(values)
            .on_conflict_do_nothing(index_elements=["campaign_id", "phone"])
            .returning(CampaignContact.phone, CampaignContact.reason)
        )
        for _, reason in stored.all():
            report.added += 1
            report.excluded += reason == EXCLUDED
            report.skipped_dnc += reason in DNC_REASONS
    report.already_in_campaign = len(rows) - report.added
    return report


async def exclude(
    session: AsyncSession, campaign: Campaign, phones: Sequence[str], reason: str | None = None
) -> int:
    """Add numbers to the campaign's exclusion list; contacts already waiting are skipped now."""
    added = 0
    for part in chunks(list(phones)):
        stored = await session.execute(
            insert(CampaignExclusion)
            .values([{"campaign_id": campaign.id, "phone": p} for p in part])
            .on_conflict_do_nothing(index_elements=["campaign_id", "phone"])
            .returning(CampaignExclusion.id)
        )
        added += len(stored.all())
        await session.execute(
            update(CampaignContact)
            .where(
                CampaignContact.campaign_id == campaign.id,
                CampaignContact.phone.in_(part),
                CampaignContact.status.in_((ContactStatus.PENDING, ContactStatus.CALLBACK)),
            )
            .values(
                status=ContactStatus.SKIPPED,
                reason=reason or EXCLUDED,
                next_attempt_at=None,
            )
        )
    return added


async def called_elsewhere(
    session: AsyncSession, campaign: Campaign, phone: str, days: int, now: datetime
) -> bool:
    """Did another campaign of this account ring this number in the last `days` days?"""
    if days <= 0:
        return False
    found = await session.scalar(
        select(Call.id)
        .join(Lead, Lead.id == Call.lead_id)
        .where(
            Call.account_id == campaign.account_id,
            Lead.phone == phone,
            Call.campaign_id.is_not(None),
            Call.campaign_id != campaign.id,
            Call.is_test.is_(False),
            Call.started_at > now - timedelta(days=days),
        )
        .limit(1)
    )
    return found is not None


async def settle(
    session: AsyncSession,
    call: Call,
    status: CallStatus,
    now: datetime,
    *,
    hold_next: bool,
) -> None:
    """A call to a contact ended: an answer finishes the contact; anything else is retried as the
    campaign says, until it runs out of attempts. `hold_next` is an outcome nobody knows (the call
    may have been answered), so the contact is never retried on a guess."""
    if call.contact_id is None or call.campaign_id is None:
        return
    contact = await session.get(CampaignContact, call.contact_id, with_for_update=True)
    campaign = await session.get(Campaign, call.campaign_id)
    if contact is None or campaign is None or contact.status is not ContactStatus.CALLING:
        return
    settings = campaign_settings.of(campaign.settings)
    contact.reason = None
    if status is CallStatus.COMPLETED:
        contact.status = ContactStatus.DONE
    elif hold_next:
        contact.status, contact.reason = ContactStatus.EXHAUSTED, UNKNOWN_OUTCOME
    elif campaign.status is CampaignStatus.CANCELED:
        contact.status, contact.reason = ContactStatus.CANCELED, "the campaign was cancelled"
    elif contact.attempts > settings.retries:
        contact.status, contact.reason = (
            ContactStatus.EXHAUSTED,
            f"no answer after {contact.attempts} attempt(s)",
        )
    else:
        contact.status = ContactStatus.PENDING
        contact.next_attempt_at = campaign_settings.retry_time(now, settings)


async def callback(session: AsyncSession, call: Call, lead: Lead, asked_for: datetime) -> None:
    """The contact asked to be called back at a time: it is called then, inside the calling hours,
    with a fresh set of attempts. A callback already waiting is not moved."""
    if call.contact_id is None or call.campaign_id is None:
        return
    contact = await session.get(CampaignContact, call.contact_id, with_for_update=True)
    campaign = await session.get(Campaign, call.campaign_id)
    if contact is None or campaign is None or contact.status is ContactStatus.CALLBACK:
        return
    if campaign.status is CampaignStatus.CANCELED:
        return
    if campaign.status is CampaignStatus.SCHEDULED and campaign.scheduled_at is not None:
        asked_for = max(asked_for, campaign.scheduled_at)  # a repeating campaign serves it then
    at = campaign_settings.next_open(asked_for, campaign_settings.of(campaign.settings))
    if campaign.status is CampaignStatus.COMPLETED:
        # The last call ended before its analysis did; the caller asked for this call, so the
        # campaign is open again until it is made.
        campaign.status, campaign.completed_at = CampaignStatus.RUNNING, None
    contact.status, contact.attempts, contact.reason = ContactStatus.CALLBACK, 0, None
    contact.next_attempt_at = at
    session.add(
        Notification(
            account_id=call.account_id,
            kind="callback_scheduled",
            title="Callback scheduled",
            body=f"{lead.name or lead.phone} asked to be called back: "
            f"{rules.local(at, rules.IST):%d %b, %H:%M} IST (campaign {campaign.name}).",
        )
    )


# --- Actions from the live panel ---------------------------------------------------------------


async def _move(
    session: AsyncSession,
    campaign: Campaign,
    take: Sequence[ContactStatus],
    *,
    only_never_called: bool = False,
) -> int:
    query = (
        update(CampaignContact)
        .where(CampaignContact.campaign_id == campaign.id, CampaignContact.status.in_(take))
        .values(
            status=ContactStatus.PENDING,
            attempts=0,
            reason=None,
            next_attempt_at=None,
            priority=False,
        )
    )
    if only_never_called:
        query = query.where(CampaignContact.attempts == 0)
    return affected(await session.execute(query))


async def retry_exhausted(session: AsyncSession, campaign: Campaign) -> int:
    """Every contact that ran out of attempts goes back to the start of the ladder."""
    return await _move(session, campaign, (ContactStatus.EXHAUSTED,))


async def restore_not_called(session: AsyncSession, campaign: Campaign) -> int:
    """Contacts that were cancelled before they were ever called come back. Skipped ones do not:
    a rule excluded them."""
    return await _move(session, campaign, (ContactStatus.CANCELED,), only_never_called=True)


async def cancel_callbacks(session: AsyncSession, campaign: Campaign) -> int:
    result = await session.execute(
        update(CampaignContact)
        .where(
            CampaignContact.campaign_id == campaign.id,
            CampaignContact.status == ContactStatus.CALLBACK,
        )
        .values(status=ContactStatus.CANCELED, reason="callback cancelled", next_attempt_at=None)
    )
    return affected(result)


async def cancel_open(session: AsyncSession, campaign: Campaign, reason: str) -> int:
    """Stop everything that has not been called: used when the campaign is cancelled. A call in
    flight is left to finish."""
    result = await session.execute(
        update(CampaignContact)
        .where(
            CampaignContact.campaign_id == campaign.id,
            CampaignContact.status.in_((ContactStatus.PENDING, ContactStatus.CALLBACK)),
        )
        .values(status=ContactStatus.CANCELED, reason=reason, next_attempt_at=None)
    )
    return affected(result)
