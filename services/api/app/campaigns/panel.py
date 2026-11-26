"""The live panel of a campaign and what the owner can do from it, the contact export, analytics,
and the capacity preview. Same prefix and scoping as `app.campaigns.router`."""

import math
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Date, cast, func, select, tuple_
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.billing.config import rate_per_minute
from app.billing.ledger import credits
from app.calls.csvsafe import to_csv
from app.campaigns import contacts, importer
from app.campaigns import settings as schedule
from app.campaigns.lists import save_list
from app.campaigns.router import counts, load_campaign
from app.db import Session
from app.employees.script import OUTCOMES
from app.instant import rules
from app.models import (
    Account,
    Call,
    CallStatus,
    Campaign,
    CampaignContact,
    CampaignStatus,
    ContactStatus,
    Employee,
    PhoneNumber,
    User,
    Voice,
    VoiceTier,
)

router = APIRouter(prefix="/campaigns")
DEFAULT_CALL_SECONDS = (
    90  # a guess for the preview until the employee has answered calls of its own
)
CALL_GAP_SECONDS = 15  # dialing and ringing between two calls on one channel
MAX_SELECTED = 500  # contacts one bulk action takes
MAX_SAVED = 2000  # contacts picked by hand for one saved list (the screen shows up to 2,000)


def reopen(campaign: Campaign, moved: int) -> None:
    """Contacts were put back on a finished campaign: it is paused, never started on its own, so
    nobody is called until the owner says resume."""
    if moved and campaign.status in (CampaignStatus.COMPLETED, CampaignStatus.CANCELED):
        campaign.status, campaign.completed_at = CampaignStatus.PAUSED, None
        campaign.note = "paused: resume to call the restored contacts"


# --- Live panel and bulk actions ---------------------------------------------------------------


@router.get("/{campaign_id}/live")
async def live(campaign_id: uuid.UUID, user: CurrentUser, session: Session) -> dict[str, Any]:
    """Calling now, callbacks waiting, done and remaining, in one read."""
    campaign = await load_campaign(session, user, campaign_id)
    by_status = await counts(session, campaign.id)
    calling = await session.execute(
        select(CampaignContact, Call)
        .join(Call, Call.contact_id == CampaignContact.id)
        .where(
            CampaignContact.campaign_id == campaign.id,
            CampaignContact.status == ContactStatus.CALLING,
            Call.status.in_((CallStatus.RINGING, CallStatus.IN_PROGRESS)),
        )
        .order_by(Call.started_at)
    )
    waiting = await session.scalars(
        select(CampaignContact)
        .where(
            CampaignContact.campaign_id == campaign.id,
            CampaignContact.status == ContactStatus.CALLBACK,
        )
        .order_by(CampaignContact.next_attempt_at)
        .limit(100)
    )
    return {
        "status": campaign.status,
        "note": campaign.note,
        "counts": by_status,
        "calling_now": [
            {
                "contact_id": c.id,
                "phone": c.phone,
                "name": c.name,
                "call_id": call.id,
                "attempt": call.attempt,
                "since": call.started_at,
            }
            for c, call in calling.all()
        ],
        "callbacks": [
            {"contact_id": c.id, "phone": c.phone, "name": c.name, "at": c.next_attempt_at}
            for c in waiting
        ],
        "done": by_status["done"],
        "remaining": by_status["pending"],
    }


@router.post("/{campaign_id}/retry-exhausted")
async def retry_exhausted(
    campaign_id: uuid.UUID, user: CurrentUser, session: Session
) -> dict[str, Any]:
    campaign = await load_campaign(session, user, campaign_id, lock=True)
    moved = await contacts.retry_exhausted(session, campaign)
    reopen(campaign, moved)
    await session.commit()
    return {"moved": moved, "status": campaign.status}


@router.post("/{campaign_id}/restore-not-called")
async def restore_not_called(
    campaign_id: uuid.UUID, user: CurrentUser, session: Session
) -> dict[str, Any]:
    campaign = await load_campaign(session, user, campaign_id, lock=True)
    moved = await contacts.restore_not_called(session, campaign)
    reopen(campaign, moved)
    await session.commit()
    return {"moved": moved, "status": campaign.status}


@router.post("/{campaign_id}/cancel-callbacks")
async def cancel_callbacks(
    campaign_id: uuid.UUID, user: CurrentUser, session: Session
) -> dict[str, int]:
    campaign = await load_campaign(session, user, campaign_id, lock=True)
    moved = await contacts.cancel_callbacks(session, campaign)
    await session.commit()
    return {"moved": moved}


async def _contact(
    session: AsyncSession, campaign: Campaign, contact_id: uuid.UUID
) -> CampaignContact:
    contact = await session.scalar(
        select(CampaignContact)
        .where(CampaignContact.id == contact_id, CampaignContact.campaign_id == campaign.id)
        .with_for_update()
    )
    if contact is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "contact not found")
    return contact


def _back_to_start(contact: CampaignContact) -> None:
    contact.status, contact.attempts, contact.reason = ContactStatus.PENDING, 0, None
    contact.next_attempt_at = None


ContactAction = Literal["call-now", "cancel", "retry"]


def _act(contact: CampaignContact, action: ContactAction) -> str | None:
    """Do `action` to one contact, or say why it cannot be done to it. The same rules serve one
    contact and a selection of them."""
    state = contact.status
    if action == "call-now":
        # First in line. The calling hours, the do-not-call list and the other checks still apply,
        # so out of hours it is called when the window opens.
        if state in (ContactStatus.EXHAUSTED, ContactStatus.CANCELED):
            _back_to_start(contact)
        elif state not in (ContactStatus.PENDING, ContactStatus.CALLBACK):
            return f"a {state.value} contact cannot be called now"
        contact.priority, contact.next_attempt_at = True, None
    elif action == "cancel":
        if state not in (ContactStatus.PENDING, ContactStatus.CALLBACK, ContactStatus.EXHAUSTED):
            return f"a {state.value} contact cannot be cancelled"
        contact.status, contact.reason, contact.next_attempt_at = (
            ContactStatus.CANCELED,
            "cancelled by a person",
            None,
        )
    else:
        # Another go from the first attempt. A skipped contact stays skipped: a rule excluded it.
        if state not in (ContactStatus.DONE, ContactStatus.EXHAUSTED, ContactStatus.CANCELED):
            return f"a {state.value} contact cannot be retried"
        _back_to_start(contact)
    return None


def _must_run(campaign: Campaign, action: ContactAction) -> None:
    if action == "call-now" and campaign.status is not CampaignStatus.RUNNING:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "the campaign is not running: resume it first"
        )


async def _one(
    session: AsyncSession,
    user: User,
    campaign_id: uuid.UUID,
    contact_id: uuid.UUID,
    action: ContactAction,
) -> tuple[Campaign, CampaignContact]:
    campaign = await load_campaign(session, user, campaign_id, lock=True)
    contact = await _contact(session, campaign, contact_id)
    _must_run(campaign, action)
    if refused := _act(contact, action):
        raise HTTPException(status.HTTP_409_CONFLICT, refused)
    if action == "retry":
        reopen(campaign, 1)
    await session.commit()
    return campaign, contact


@router.post("/{campaign_id}/contacts/{contact_id}/call-now")
async def call_now(
    campaign_id: uuid.UUID, contact_id: uuid.UUID, user: CurrentUser, session: Session
) -> dict[str, Any]:
    campaign, _ = await _one(session, user, campaign_id, contact_id, "call-now")
    now = datetime.now(UTC)
    return {"dials_at": schedule.next_open(now, schedule.of(campaign.settings))}


@router.post("/{campaign_id}/contacts/{contact_id}/cancel")
async def cancel_contact(
    campaign_id: uuid.UUID, contact_id: uuid.UUID, user: CurrentUser, session: Session
) -> dict[str, Any]:
    _, contact = await _one(session, user, campaign_id, contact_id, "cancel")
    return {"status": contact.status}


@router.post("/{campaign_id}/contacts/{contact_id}/retry")
async def retry_contact(
    campaign_id: uuid.UUID, contact_id: uuid.UUID, user: CurrentUser, session: Session
) -> dict[str, Any]:
    campaign, contact = await _one(session, user, campaign_id, contact_id, "retry")
    return {"status": contact.status, "campaign_status": campaign.status}


class BulkBody(BaseModel):
    contact_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_SELECTED)
    action: ContactAction


@router.post("/{campaign_id}/contacts/bulk")
async def bulk(
    campaign_id: uuid.UUID, body: BulkBody, user: CurrentUser, session: Session
) -> dict[str, Any]:
    """Call now, cancel or retry the selected contacts, with the same rules as one at a time. A
    contact the action does not fit is left as it is and listed with the reason."""
    campaign = await load_campaign(session, user, campaign_id, lock=True)
    _must_run(campaign, body.action)
    wanted = list(dict.fromkeys(body.contact_ids))
    found = {
        c.id: c
        for c in await session.scalars(
            select(CampaignContact)
            .where(CampaignContact.campaign_id == campaign.id, CampaignContact.id.in_(wanted))
            .order_by(CampaignContact.id)
            .with_for_update()
        )
    }
    done, refused = 0, []
    for contact_id in wanted:
        contact = found.get(contact_id)
        reason = "contact not found" if contact is None else _act(contact, body.action)
        if reason is None:
            done += 1
        else:
            refused.append({"contact_id": contact_id, "reason": reason})
    if body.action == "retry":
        reopen(campaign, done)
    await session.commit()
    return {"done": done, "refused": refused, "campaign_status": campaign.status}


class SaveAsList(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # Which contacts: the ones selected, and/or every one in a state or whose last call ended
    # with an outcome. Nothing given saves the whole campaign.
    contact_ids: list[uuid.UUID] | None = Field(default=None, min_length=1, max_length=MAX_SAVED)
    state: ContactStatus | None = None
    outcome: str | None = None

    @field_validator("outcome")
    @classmethod
    def _outcome(cls, outcome: str | None) -> str | None:
        if outcome is not None and outcome not in OUTCOMES:
            raise ValueError(f"outcome is one of {', '.join(OUTCOMES)}")
        return outcome


@router.post("/{campaign_id}/contacts/save-as-list", status_code=status.HTTP_201_CREATED)
async def save_as_list(
    campaign_id: uuid.UUID, body: SaveAsList, user: CurrentUser, session: Session
) -> dict[str, Any]:
    """Keep some of this campaign's contacts as a saved list (for example everyone who asked to be
    called back), with their details, to start another campaign from. A list of that name is added
    to. The do-not-call list is checked again when the list is used."""
    campaign = await load_campaign(session, user, campaign_id)
    query = select(CampaignContact).where(CampaignContact.campaign_id == campaign.id)
    if body.contact_ids is not None:
        query = query.where(CampaignContact.id.in_(body.contact_ids))
    if body.state is not None:
        query = query.where(CampaignContact.status == body.state)
    if body.outcome is not None:
        last = (
            select(Call.contact_id, Call.outcome)
            .where(Call.campaign_id == campaign.id, Call.contact_id.is_not(None))
            .ext(distinct_on(Call.contact_id))
            .order_by(Call.contact_id, Call.created_at.desc())
            .subquery()
        )
        query = query.join(last, last.c.contact_id == CampaignContact.id).where(
            last.c.outcome == body.outcome
        )
    rows = [
        importer.Row(c.phone, c.name, dict(c.variables))
        for c in await session.scalars(query.order_by(CampaignContact.created_at))
    ]
    if not rows:
        raise HTTPException(status.HTTP_409_CONFLICT, "no contacts match: nothing was saved")
    saved = await save_list(session, user, body.name, rows)
    await session.commit()
    return {"list_id": saved.id, "name": saved.name, "contacts": len(rows)}


# --- Export ------------------------------------------------------------------------------------


@router.get("/{campaign_id}/export.csv")
async def export(campaign_id: uuid.UUID, user: CurrentUser, session: Session) -> Response:
    campaign = await load_campaign(session, user, campaign_id)
    last = {
        call.contact_id: call
        for call in await session.scalars(
            select(Call)
            .where(Call.campaign_id == campaign.id, Call.contact_id.is_not(None))
            .ext(distinct_on(Call.contact_id))
            .order_by(Call.contact_id, Call.created_at.desc())
        )
    }
    rows = list(
        await session.scalars(
            select(CampaignContact)
            .where(CampaignContact.campaign_id == campaign.id)
            .order_by(CampaignContact.created_at, CampaignContact.id)
        )
    )
    keys = sorted({k for c in rows for k in c.variables})
    header = [
        "phone",
        "name",
        "status",
        "attempts",
        "reason",
        "next_attempt_at",
        "last_call_status",
        "last_call_outcome",
        "last_call_seconds",
        *keys,
    ]
    body = []
    for c in rows:
        call = last.get(c.id)
        body.append(
            [
                c.phone,
                c.name,
                c.status.value,
                c.attempts,
                c.reason,
                c.next_attempt_at,
                call.status.value if call else None,
                call.outcome if call else None,
                call.duration_s if call else None,
                *[c.variables.get(k) for k in keys],
            ]
        )
    return Response(
        to_csv(header, body),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="campaign-{campaign.id}.csv"'},
    )


# --- Analytics ---------------------------------------------------------------------------------


@router.get("/{campaign_id}/analytics")
async def analytics(campaign_id: uuid.UUID, user: CurrentUser, session: Session) -> dict[str, Any]:
    campaign = await load_campaign(session, user, campaign_id)
    real = (Call.campaign_id == campaign.id, Call.is_test.is_(False))
    attempts, answered, seconds, spent = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(Call.status == CallStatus.COMPLETED),
                func.coalesce(
                    func.avg(Call.duration_s).filter(Call.status == CallStatus.COMPLETED), 0
                ),
                func.coalesce(func.sum(Call.credits_charged), 0),
            ).where(*real, Call.status.not_in((CallStatus.QUEUED, CallStatus.RINGING)))
        )
    ).one()
    by_outcome = dict(
        (
            await session.execute(
                select(Call.outcome, func.count())
                .where(*real, Call.outcome.is_not(None))
                .group_by(Call.outcome)
            )
        ).all()
    )
    by_sentiment = dict(
        (
            await session.execute(
                select(Call.sentiment, func.count())
                .where(*real, Call.sentiment.is_not(None))
                .group_by(Call.sentiment)
            )
        ).all()
    )
    day = cast(func.timezone("UTC", Call.started_at) + timedelta(minutes=rules.IST), Date)
    per_day = await session.execute(
        select(day, func.count(), func.count().filter(Call.status == CallStatus.COMPLETED))
        .where(*real, Call.started_at.is_not(None))
        .group_by(day)
        .order_by(day)
    )
    by_contact = await counts(session, campaign.id)
    reached = by_contact["done"]
    return {
        "contacts": by_contact,
        "attempts": attempts,
        "answered_calls": answered,
        "answer_rate": round(answered / attempts, 4) if attempts else 0,
        "contacts_reached": reached,
        "avg_talk_seconds": round(float(seconds), 1),
        "credits_spent": str(credits(Decimal(spent))),
        "outcomes": by_outcome,
        "sentiment": by_sentiment,
        "by_day": [
            {"date": d.isoformat(), "attempts": a, "answered": n}
            for d, a, n in per_day.all()
            if isinstance(d, date)
        ],
    }


# --- Capacity preview and queue ----------------------------------------------------------------


@router.get("/{campaign_id}/capacity")
async def capacity(campaign_id: uuid.UUID, user: CurrentUser, session: Session) -> dict[str, Any]:
    """How long the campaign will take and about what it costs, before (or while) it runs. An
    estimate: talk time comes from the employee's answered calls, or 90 s until it has some."""
    campaign = await load_campaign(session, user, campaign_id)
    settings = schedule.of(campaign.settings)
    employee = await session.get(Employee, campaign.employee_id)
    assert employee is not None  # FK guarantees it
    number = await session.get(PhoneNumber, employee.number_id) if employee.number_id else None
    by_status = await counts(session, campaign.id)
    remaining = by_status["pending"] + by_status["callback"]
    avg = await session.scalar(
        select(func.avg(Call.duration_s)).where(
            Call.employee_id == employee.id,
            Call.status == CallStatus.COMPLETED,
            Call.is_test.is_(False),
            Call.duration_s > 0,
        )
    )
    talk = float(avg) if avg else float(DEFAULT_CALL_SECONDS)
    channels_n = number.channels if number else 0
    lanes = min(settings.concurrency, channels_n)
    per_lane_day = schedule.window_minutes(settings) * 60 / (talk + CALL_GAP_SECONDS)
    per_day = int(lanes * per_lane_day)
    open_days = len(settings.days)
    calls_needed = remaining * (1 + settings.retries * 0.5)  # retries are a guess: half need one
    working_days = math.ceil(calls_needed / per_day) if per_day else None
    voice = await session.get(Voice, employee.voice_id) if employee.voice_id else None
    rate = rate_per_minute(voice.tier if voice else VoiceTier.VALUE)
    account = await session.get(Account, campaign.account_id)
    assert account is not None  # FK guarantees it
    cost = credits(rate * Decimal(str(talk)) / 60 * remaining)
    ahead = list(
        await session.scalars(
            select(Campaign.name)
            .where(
                Campaign.employee_id == campaign.employee_id,
                Campaign.status == CampaignStatus.RUNNING,
                Campaign.id != campaign.id,
                tuple_(Campaign.created_at, Campaign.id) < tuple_(campaign.created_at, campaign.id),
            )
            .order_by(Campaign.created_at)
        )
    )
    return {
        "remaining_contacts": remaining,
        "number_channels": channels_n,
        "concurrency": settings.concurrency,
        "parallel_calls": lanes,
        "avg_talk_seconds": round(talk, 1),
        "calls_per_open_day": per_day,
        "open_days_per_week": open_days,
        "working_days_needed": working_days,
        "estimated_cost": str(cost),  # if every contact is answered and talks as long as average
        "credit_balance": str(account.credit_balance),
        "enough_credits": account.credit_balance >= cost,
        "queue_ahead": ahead,  # older running campaigns on the same number take channels first
    }
