"""The campaign scheduler: start what is due, place the calls that may be placed, finish what is
done. `tick` is a plain function of the database, the telephony adapter and `now`, so the worker is
only the clock and the tests can run a campaign through a whole week.

Campaigns are served oldest first, and they share the channels of their employee's number: the
oldest campaign takes the free channels it may use, the next one gets what is left. Every contact
is checked again just before it is dialed (do-not-call, exclusion list, another campaign's recent
call, free channel, credits, dial rule); a check made at upload time is not enough, because the
world moves between the upload and the call.
"""

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.billing import policy as credit_policy
from app.campaigns import contacts
from app.campaigns import settings as schedule
from app.campaigns.settings import CampaignSettings
from app.instant import dialer, policy, rules
from app.models import (
    Call,
    CallEvent,
    CallStatus,
    Campaign,
    CampaignContact,
    CampaignStatus,
    Channel,
    ContactStatus,
    Direction,
    Employee,
    EmployeeStatus,
    Lead,
    Notification,
    PhoneNumber,
)
from app.numbers import channels
from app.providers.base import TelephonyProvider
from app.settings import api_public_url, engine_public_url

BATCH = 20  # calls placed per tick, across all campaigns
PASSES = 5  # looks at a campaign's waiting contacts per tick (skipped ones free their place)
MAX_RERUN_STEPS = 400


def _ist(at: datetime) -> str:
    return f"{rules.local(at, rules.IST):%d %b, %H:%M} IST"


async def tick(
    factory: async_sessionmaker[AsyncSession],
    telephony: TelephonyProvider,
    now: datetime,
    *,
    limit: int = BATCH,
) -> list[dialer.Dialed]:
    """One round: start the campaigns whose time has come, place due calls, close finished ones.
    Raises ProviderNotConfiguredError (503) if the public URLs the carrier needs are not set."""
    engine_url, api_url = engine_public_url(), api_public_url()
    async with factory() as session:
        await activate_due(session, now)
        await session.commit()
    claimed = await claim(factory, now, limit)
    placed = await dialer.place(factory, telephony, claimed, now, engine_url, api_url)
    async with factory() as session:
        await finish_done(session, now)
        await session.commit()
    return placed


async def activate_due(session: AsyncSession, now: datetime) -> int:
    due = list(
        await session.scalars(
            select(Campaign)
            .where(Campaign.status == CampaignStatus.SCHEDULED, Campaign.scheduled_at <= now)
            .with_for_update()
        )
    )  # loaded, not bulk-updated: the change is announced to the webhooks when it is flushed
    for campaign in due:
        campaign.status, campaign.started_at, campaign.note = CampaignStatus.RUNNING, now, None
    return len(due)


async def claim(
    factory: async_sessionmaker[AsyncSession], now: datetime, limit: int
) -> list[dialer.Claim]:
    """Decide every due contact in one transaction and mark the ones to dial as ringing before any
    slow carrier call. The campaign rows are locked in age order, so two workers take turns."""
    out: list[dialer.Claim] = []
    async with factory() as session:
        running = await session.scalars(
            select(Campaign)
            .where(Campaign.status == CampaignStatus.RUNNING)
            .order_by(Campaign.created_at, Campaign.id)
            .with_for_update()
        )
        for campaign in running:
            if len(out) >= limit:
                break
            out += await _serve(session, campaign, now, limit - len(out))
        await session.commit()
    return out


async def _gate(
    session: AsyncSession, campaign: Campaign, now: datetime
) -> tuple[Employee, PhoneNumber] | None:
    """May this campaign dial at all right now? If not, `campaign.note` says why in plain words
    (a rule that refuses the calls pauses the campaign instead of retrying forever)."""
    settings = schedule.of(campaign.settings)
    employee = await session.get(Employee, campaign.employee_id)
    number = (
        await session.get(PhoneNumber, employee.number_id)
        if employee is not None and employee.number_id
        else None
    )
    campaign.note = None
    if employee is None or employee.status is not EmployeeStatus.LIVE:
        campaign.note = "the employee is not live"
        return None
    if number is None:
        campaign.note = "the employee has no phone number"
        return None
    if not schedule.in_window(now, settings):
        campaign.note = (
            f"outside calling hours; calls resume {_ist(schedule.next_open(now, settings))}"
        )
        return None
    if held := await credit_policy.blocked_reason(session, campaign.account_id, now):
        campaign.note = held
        return None
    verdict = await policy.check_dial(session, employee, number, "outbound", campaign.purpose)
    if not verdict.allowed:
        campaign.status, campaign.note = CampaignStatus.PAUSED, verdict.reason
        session.add(
            Notification(
                account_id=campaign.account_id,
                kind="campaign_paused",
                title=f"Campaign {campaign.name} paused",
                body=verdict.reason,
            )
        )
        return None
    return employee, number


async def _serve(
    session: AsyncSession, campaign: Campaign, now: datetime, room: int
) -> list[dialer.Claim]:
    gate = await _gate(session, campaign, now)
    if gate is None:
        return []
    employee, number = gate
    settings = schedule.of(campaign.settings)
    calling = int(
        await session.scalar(
            select(func.count()).where(
                CampaignContact.campaign_id == campaign.id,
                CampaignContact.status == ContactStatus.CALLING,
            )
        )
        or 0
    )
    slots = min(settings.concurrency - calling, room)
    out: list[dialer.Claim] = []
    for _ in range(PASSES):
        if slots <= 0:
            break
        due = list(await _due(session, campaign, now, slots))
        if not due:
            break
        for contact in due:
            if await _skip_reason(session, campaign, contact, settings, now):
                continue
            if not await channels.has_free_channel(session, number):
                campaign.note = "waiting for a free channel on the number"
                return out
            out.append(await _start(session, campaign, contact, employee, number, now))
            slots -= 1
    return out


async def _due(
    session: AsyncSession, campaign: Campaign, now: datetime, count: int
) -> list[CampaignContact]:
    return list(
        await session.scalars(
            select(CampaignContact)
            .where(
                CampaignContact.campaign_id == campaign.id,
                CampaignContact.status.in_((ContactStatus.PENDING, ContactStatus.CALLBACK)),
                (CampaignContact.next_attempt_at.is_(None))
                | (CampaignContact.next_attempt_at <= now),
            )
            .order_by(
                CampaignContact.priority.desc(),
                func.coalesce(CampaignContact.next_attempt_at, CampaignContact.created_at),
                CampaignContact.id,
            )
            .limit(count)
            .with_for_update(skip_locked=True)
        )
    )


async def _skip_reason(
    session: AsyncSession,
    campaign: Campaign,
    contact: CampaignContact,
    settings: CampaignSettings,
    now: datetime,
) -> str | None:
    """Skip the contact (for good) if a rule says it must not be called; return the reason."""
    reason: str | None = None
    if await contacts.excluded_phones(session, campaign.id, [contact.phone]):
        reason = contacts.EXCLUDED
    elif dnc := await contacts.dnc_reasons(
        session, campaign.account_id, [contact.phone], settings.skip_dnc
    ):
        reason = dnc[contact.phone]
    elif await contacts.called_elsewhere(
        session, campaign, contact.phone, settings.dedupe_days, now
    ):
        reason = f"another campaign called this number in the last {settings.dedupe_days} day(s)"
    if reason is not None:
        contact.status, contact.reason, contact.next_attempt_at = (
            ContactStatus.SKIPPED,
            reason,
            None,
        )
    return reason


async def _lead_of(session: AsyncSession, campaign: Campaign, contact: CampaignContact) -> Lead:
    """The account's lead for this number (the call row points at it), made if it is new."""
    await session.execute(
        insert(Lead)
        .values(account_id=campaign.account_id, phone=contact.phone, name=contact.name)
        .on_conflict_do_nothing(index_elements=["account_id", "phone"])
    )
    lead = await session.scalar(
        select(Lead).where(Lead.account_id == campaign.account_id, Lead.phone == contact.phone)
    )
    assert lead is not None  # just inserted or already there
    if contact.name and not lead.name:
        lead.name = contact.name
    return lead


async def _start(
    session: AsyncSession,
    campaign: Campaign,
    contact: CampaignContact,
    employee: Employee,
    number: PhoneNumber,
    now: datetime,
) -> dialer.Claim:
    lead = await _lead_of(session, campaign, contact)
    contact.attempts += 1
    contact.status, contact.priority, contact.next_attempt_at = ContactStatus.CALLING, False, None
    call = Call(
        account_id=campaign.account_id,
        employee_id=employee.id,
        lead_id=lead.id,
        campaign_id=campaign.id,
        contact_id=contact.id,
        number_id=number.id,
        direction=Direction.OUTBOUND,
        channel=Channel.BULK,
        status=CallStatus.RINGING,
        started_at=now,
        attempt=contact.attempts,
    )
    session.add(call)
    await session.flush()
    session.add(CallEvent(call_id=call.id, type="campaign_dial", data={"campaign": campaign.name}))
    return dialer.Claim(call.id, "dial", employee.id, number.e164, contact.phone)


async def finish_done(session: AsyncSession, now: datetime) -> int:
    """A running campaign with nothing left to call is complete; a repeating one is set up for its
    next run instead: finished contacts go back to the start and it waits for its day."""
    finished = list(
        await session.scalars(
            select(Campaign)
            .where(
                Campaign.status == CampaignStatus.RUNNING,
                ~select(CampaignContact.id)
                .where(
                    CampaignContact.campaign_id == Campaign.id,
                    CampaignContact.status.in_(contacts.OPEN),
                )
                .exists(),
            )
            .with_for_update()
        )
    )
    for campaign in finished:
        settings = schedule.of(campaign.settings)
        campaign.completed_at, campaign.note = now, None
        if settings.repeat == "none":
            campaign.status = CampaignStatus.COMPLETED
            continue
        await _rearm(session, campaign, settings, now)
    return len(finished)


async def _rearm(
    session: AsyncSession, campaign: Campaign, settings: CampaignSettings, now: datetime
) -> None:
    at = campaign.scheduled_at or campaign.started_at or now
    for _ in range(MAX_RERUN_STEPS):
        nxt = schedule.next_run(at, settings)
        assert nxt is not None  # repeat is not "none"
        at = nxt
        if at > now:
            break
    campaign.status, campaign.scheduled_at = CampaignStatus.SCHEDULED, at
    await session.execute(
        update(CampaignContact)
        .where(
            CampaignContact.campaign_id == campaign.id,
            CampaignContact.status.in_((ContactStatus.DONE, ContactStatus.EXHAUSTED)),
            # A call nobody knows the result of stays held until a person has checked it.
            CampaignContact.reason.is_distinct_from(contacts.UNKNOWN_OUTCOME),
        )
        .values(
            status=ContactStatus.PENDING,
            attempts=0,
            reason=None,
            next_attempt_at=None,
            priority=False,
        )
    )
    session.add(
        Notification(
            account_id=campaign.account_id,
            kind="campaign_rescheduled",
            title=f"Campaign {campaign.name} finished a run",
            body=f"It runs again {_ist(at)}.",
        )
    )
