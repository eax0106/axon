"""Campaign endpoints, all scoped to the caller's account: create and edit, the owner's consent,
adding contacts (CSV, paste, manual, saved list), the exclusion list, and start, pause, resume and
cancel. The live panel, export, analytics and capacity are in `app.campaigns.panel`."""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.campaigns import contacts, importer
from app.campaigns import settings as schedule
from app.campaigns.lists import load_list, save_list
from app.campaigns.settings import CampaignSettings
from app.db import Session
from app.employees import service as employees
from app.employees.router import OwnerUser, load
from app.instant import policy
from app.models import (
    Campaign,
    CampaignContact,
    CampaignExclusion,
    CampaignStatus,
    Channel,
    ConsentAttestation,
    ConsentScope,
    ContactListItem,
    ContactStatus,
    Employee,
    EmployeeStatus,
    PhoneNumber,
    Purpose,
    User,
)

router = APIRouter(prefix="/campaigns")

CONSENT_STATEMENT = (
    "I confirm that the people on this list agreed to receive calls from my business, or that I "
    "may lawfully call them, and that I will honour the do-not-call list."
)
EDITABLE = (CampaignStatus.DRAFT, CampaignStatus.SCHEDULED, CampaignStatus.PAUSED)
CLOSED = (CampaignStatus.COMPLETED, CampaignStatus.CANCELED)


async def load_campaign(
    session: AsyncSession, user: User, campaign_id: uuid.UUID, *, lock: bool = False
) -> Campaign:
    """The campaign, only if it belongs to the caller's account (otherwise 404, never 403)."""
    query = select(Campaign).where(
        Campaign.id == campaign_id, Campaign.account_id == user.account_id
    )
    campaign = await session.scalar(query.with_for_update() if lock else query)
    if campaign is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "campaign not found")
    return campaign


async def counts(session: AsyncSession, campaign_id: uuid.UUID) -> dict[str, int]:
    """Contacts by status; every status is present, so a client can rely on the keys."""
    found = dict(
        (
            await session.execute(
                select(CampaignContact.status, func.count())
                .where(CampaignContact.campaign_id == campaign_id)
                .group_by(CampaignContact.status)
            )
        ).all()
    )
    return {s.value: int(found.get(s, 0)) for s in ContactStatus}


class CampaignOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    name: str
    purpose: Purpose | None
    status: CampaignStatus
    settings: CampaignSettings
    scheduled_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    note: str | None
    created_at: datetime
    contacts: dict[str, int]
    consent_given: bool


async def out(session: AsyncSession, campaign: Campaign) -> CampaignOut:
    given = await session.scalar(
        select(ConsentAttestation.id)
        .where(
            ConsentAttestation.scope == ConsentScope.CAMPAIGN,
            ConsentAttestation.subject_id == campaign.id,
        )
        .limit(1)
    )
    return CampaignOut(
        id=campaign.id,
        employee_id=campaign.employee_id,
        name=campaign.name,
        purpose=campaign.purpose,
        status=campaign.status,
        settings=schedule.of(campaign.settings),
        scheduled_at=campaign.scheduled_at,
        started_at=campaign.started_at,
        completed_at=campaign.completed_at,
        note=campaign.note,
        created_at=campaign.created_at,
        contacts=await counts(session, campaign.id),
        consent_given=given is not None,
    )


async def bulk_employee(session: AsyncSession, user: User, employee_id: uuid.UUID) -> Employee:
    employee = await load(session, user, employee_id)
    if employee.channel is not Channel.BULK:
        raise HTTPException(status.HTTP_409_CONFLICT, "this employee is not on the Bulk channel")
    return employee


class CampaignCreate(BaseModel):
    employee_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    purpose: Purpose | None = None  # overrides the employee's purpose for this campaign
    settings: CampaignSettings = Field(default_factory=CampaignSettings)


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    purpose: Purpose | None = None
    settings: CampaignSettings | None = None


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(body: CampaignCreate, user: CurrentUser, session: Session) -> CampaignOut:
    employee = await bulk_employee(session, user, body.employee_id)
    campaign = Campaign(
        account_id=user.account_id,
        employee_id=employee.id,
        name=body.name,
        purpose=body.purpose,
        settings=body.settings.model_dump(mode="json"),
    )
    session.add(campaign)
    await session.commit()
    return await out(session, campaign)


@router.get("")
async def list_campaigns(
    user: CurrentUser,
    session: Session,
    employee_id: uuid.UUID | None = None,
    state: CampaignStatus | None = None,
) -> list[CampaignOut]:
    query = (
        select(Campaign)
        .where(Campaign.account_id == user.account_id)
        .order_by(Campaign.created_at.desc())
    )
    if employee_id:
        query = query.where(Campaign.employee_id == employee_id)
    if state:
        query = query.where(Campaign.status == state)
    return [await out(session, c) for c in await session.scalars(query)]


@router.get("/{campaign_id}")
async def get_campaign(campaign_id: uuid.UUID, user: CurrentUser, session: Session) -> CampaignOut:
    return await out(session, await load_campaign(session, user, campaign_id))


@router.patch("/{campaign_id}")
async def update(
    campaign_id: uuid.UUID, body: CampaignUpdate, user: CurrentUser, session: Session
) -> CampaignOut:
    campaign = await load_campaign(session, user, campaign_id, lock=True)
    if campaign.status not in EDITABLE:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "pause the campaign before changing it; a finished one is fixed",
        )
    if body.name is not None:
        campaign.name = body.name
    if "purpose" in body.model_fields_set:
        campaign.purpose = body.purpose
    if body.settings is not None:
        campaign.settings = body.settings.model_dump(mode="json")
    await session.commit()
    return await out(session, campaign)


class Consent(BaseModel):
    confirm: Literal[True]


@router.post("/{campaign_id}/consent", status_code=status.HTTP_201_CREATED)
async def give_consent(
    campaign_id: uuid.UUID, body: Consent, user: OwnerUser, session: Session
) -> dict[str, Any]:
    """The owner confirms the list may be called. The statement they agreed to is stored word for
    word, with who and when; a campaign does not start without it."""
    campaign = await load_campaign(session, user, campaign_id)
    entry = ConsentAttestation(
        account_id=user.account_id,
        user_id=user.id,
        scope=ConsentScope.CAMPAIGN,
        subject_id=campaign.id,
        statement=CONSENT_STATEMENT,
    )
    session.add(entry)
    await session.commit()
    return {"statement": entry.statement, "at": entry.created_at}


@router.get("/{campaign_id}/consent")
async def get_consent(
    campaign_id: uuid.UUID, user: CurrentUser, session: Session
) -> list[dict[str, Any]]:
    campaign = await load_campaign(session, user, campaign_id)
    rows = await session.scalars(
        select(ConsentAttestation)
        .where(
            ConsentAttestation.scope == ConsentScope.CAMPAIGN,
            ConsentAttestation.subject_id == campaign.id,
        )
        .order_by(ConsentAttestation.created_at)
    )
    return [{"user_id": r.user_id, "statement": r.statement, "at": r.created_at} for r in rows]


# --- Lifecycle ---------------------------------------------------------------------------------


class StartBody(BaseModel):
    start_at: datetime | None = Field(default=None, description="Start later; omit to start now")


@router.post("/{campaign_id}/start")
async def start(
    campaign_id: uuid.UUID, user: CurrentUser, session: Session, body: StartBody | None = None
) -> CampaignOut:
    campaign = await load_campaign(session, user, campaign_id, lock=True)
    if campaign.status is not CampaignStatus.DRAFT:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"a {campaign.status.value} campaign cannot start"
        )
    if not (await out(session, campaign)).consent_given:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "the owner has to confirm consent for this list first"
        )
    waiting = await session.scalar(
        select(func.count()).where(
            CampaignContact.campaign_id == campaign.id,
            CampaignContact.status.in_(contacts.OPEN),
        )
    )
    if not waiting:
        raise HTTPException(status.HTTP_409_CONFLICT, "add contacts before starting")
    employee = await session.get(Employee, campaign.employee_id)
    number = (
        await session.get(PhoneNumber, employee.number_id)
        if employee is not None and employee.number_id
        else None
    )
    if employee is None or employee.status is not EmployeeStatus.LIVE or number is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "the employee has to be live and have a phone number"
        )
    verdict = await policy.check_dial(session, employee, number, "outbound", campaign.purpose)
    if not verdict.allowed:
        raise HTTPException(status.HTTP_409_CONFLICT, verdict.reason)
    now = datetime.now(UTC)
    start_at = body.start_at if body else None
    if start_at is not None and start_at > now:
        campaign.status, campaign.scheduled_at = CampaignStatus.SCHEDULED, start_at
    else:
        campaign.status, campaign.started_at, campaign.scheduled_at = (
            CampaignStatus.RUNNING,
            now,
            None,
        )
    await session.commit()
    return await out(session, campaign)


async def _transition(
    session: AsyncSession,
    user: User,
    campaign_id: uuid.UUID,
    allowed: tuple[CampaignStatus, ...],
    to: CampaignStatus,
    verb: str,
) -> Campaign:
    campaign = await load_campaign(session, user, campaign_id, lock=True)
    if campaign.status not in allowed:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"a {campaign.status.value} campaign cannot be {verb}"
        )
    campaign.status = to
    return campaign


@router.post("/{campaign_id}/pause")
async def pause(campaign_id: uuid.UUID, user: CurrentUser, session: Session) -> CampaignOut:
    campaign = await _transition(
        session, user, campaign_id, (CampaignStatus.RUNNING,), CampaignStatus.PAUSED, "paused"
    )
    campaign.note = "paused"
    await session.commit()
    return await out(session, campaign)


@router.post("/{campaign_id}/resume")
async def resume(campaign_id: uuid.UUID, user: CurrentUser, session: Session) -> CampaignOut:
    campaign = await _transition(
        session, user, campaign_id, (CampaignStatus.PAUSED,), CampaignStatus.RUNNING, "resumed"
    )
    campaign.note = None
    campaign.started_at = campaign.started_at or datetime.now(UTC)
    await session.commit()
    return await out(session, campaign)


@router.post("/{campaign_id}/cancel")
async def cancel(campaign_id: uuid.UUID, user: CurrentUser, session: Session) -> CampaignOut:
    """Stop the campaign: nobody else is called. A call already under way finishes."""
    campaign = await _transition(
        session,
        user,
        campaign_id,
        (
            CampaignStatus.DRAFT,
            CampaignStatus.SCHEDULED,
            CampaignStatus.RUNNING,
            CampaignStatus.PAUSED,
        ),
        CampaignStatus.CANCELED,
        "cancelled",
    )
    campaign.note, campaign.completed_at = None, datetime.now(UTC)
    await contacts.cancel_open(session, campaign, "the campaign was cancelled")
    await session.commit()
    return await out(session, campaign)


# --- Contacts ----------------------------------------------------------------------------------


def declared_variables(employee: Employee) -> list[str]:
    return list(employees.bundle_of(employee).pre_call_variables)


async def open_campaign(
    session: AsyncSession, user: User, campaign_id: uuid.UUID
) -> tuple[Campaign, Employee]:
    """The campaign and its employee, for adding contacts to a campaign that can still call."""
    campaign = await load_campaign(session, user, campaign_id, lock=True)
    if campaign.status in CLOSED:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"a {campaign.status.value} campaign takes no more contacts"
        )
    employee = await session.get(Employee, campaign.employee_id)
    assert employee is not None  # FK guarantees it
    return campaign, employee


class PreviewBody(BaseModel):
    text: str = Field(max_length=importer.MAX_TEXT)


@router.post("/{campaign_id}/contacts/preview")
async def preview(
    campaign_id: uuid.UUID, body: PreviewBody, user: CurrentUser, session: Session
) -> dict[str, Any]:
    """Read a CSV's header and first rows so the caller can say which column is which. Nothing is
    saved and nothing is guessed."""
    campaign = await load_campaign(session, user, campaign_id)
    employee = await session.get(Employee, campaign.employee_id)
    assert employee is not None
    try:
        header, rows = importer.read_table(body.text)
    except importer.MappingError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "columns": header,
        "rows": len(rows),
        "sample": [dict(zip(header, r, strict=False)) for r in rows[:5]],
        "variables_to_map": declared_variables(employee),
    }


class ImportBody(BaseModel):
    format: Literal["csv", "paste"] = "csv"
    text: str = Field(max_length=importer.MAX_TEXT)
    mapping: importer.Mapping | None = None
    save_as_list: str | None = Field(default=None, min_length=1, max_length=200)


def report_of(added: contacts.Added, parsed: importer.Parsed) -> dict[str, Any]:
    return {
        "added": added.added,
        "already_in_campaign": added.already_in_campaign,
        "skipped_do_not_call": added.skipped_dnc,
        "skipped_excluded": added.excluded,
        "duplicates_in_file": parsed.duplicates,
        "invalid": [
            {"row": r.row, "value": r.value, "reason": r.reason} for r in parsed.invalid[:200]
        ],
        "invalid_count": len(parsed.invalid),
    }


@router.post("/{campaign_id}/contacts/import")
async def import_contacts(
    campaign_id: uuid.UUID, body: ImportBody, user: CurrentUser, session: Session
) -> dict[str, Any]:
    campaign, employee = await open_campaign(session, user, campaign_id)
    try:
        if body.format == "paste":
            parsed = importer.parse_paste(body.text)
        elif body.mapping is None:
            raise importer.MappingError("say which column holds the phone number (mapping)")
        else:
            parsed = importer.parse_csv(body.text, body.mapping, declared_variables(employee))
    except importer.MappingError as exc:
        raise HTTPException(422, str(exc)) from exc
    now = datetime.now(UTC)
    added = await contacts.add_rows(session, campaign, parsed.rows, now)
    saved = None
    if body.save_as_list:
        saved = await save_list(session, user, body.save_as_list, parsed.rows)
    await session.commit()
    return {**report_of(added, parsed), "list_id": saved.id if saved else None}


class ContactIn(BaseModel):
    phone: str = Field(max_length=40)
    name: str | None = Field(default=None, max_length=200)
    variables: dict[str, str] = Field(default_factory=dict, max_length=50)


@router.post("/{campaign_id}/contacts")
async def add_manual(
    campaign_id: uuid.UUID,
    body: Annotated[list[ContactIn], Field(min_length=1, max_length=100)],
    user: CurrentUser,
    session: Session,
) -> dict[str, Any]:
    """Type contacts in by hand (up to 100 at a time)."""
    campaign, employee = await open_campaign(session, user, campaign_id)
    declared = declared_variables(employee)
    try:
        rows = [importer.one(c.phone, c.name, c.variables, declared) for c in body]
    except importer.MappingError as exc:
        raise HTTPException(422, str(exc)) from exc
    unique = list({r.phone: r for r in rows}.values())
    added = await contacts.add_rows(session, campaign, unique, datetime.now(UTC))
    await session.commit()
    return report_of(added, importer.Parsed(rows=unique, duplicates=len(rows) - len(unique)))


class FromList(BaseModel):
    list_id: uuid.UUID


@router.post("/{campaign_id}/contacts/from-list")
async def add_from_list(
    campaign_id: uuid.UUID, body: FromList, user: CurrentUser, session: Session
) -> dict[str, Any]:
    """Start from a saved list. Only the variables the script declares are carried over."""
    campaign, employee = await open_campaign(session, user, campaign_id)
    saved = await load_list(session, user, body.list_id)
    declared = set(declared_variables(employee))
    items = await session.scalars(
        select(ContactListItem)
        .where(ContactListItem.list_id == saved.id)
        .order_by(ContactListItem.phone)
    )
    rows = [
        importer.Row(i.phone, i.name, {k: v for k, v in i.variables.items() if k in declared})
        for i in items
    ]
    added = await contacts.add_rows(session, campaign, rows, datetime.now(UTC))
    await session.commit()
    return report_of(added, importer.Parsed(rows=rows))


@router.get("/{campaign_id}/contacts")
async def list_contacts(
    campaign_id: uuid.UUID,
    user: CurrentUser,
    session: Session,
    state: ContactStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    campaign = await load_campaign(session, user, campaign_id)
    query = select(CampaignContact).where(CampaignContact.campaign_id == campaign.id)
    if state:
        query = query.where(CampaignContact.status == state)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.scalars(
        query.order_by(CampaignContact.created_at, CampaignContact.id).limit(limit).offset(offset)
    )
    return {"total": total, "contacts": [contact_out(c) for c in rows]}


def contact_out(c: CampaignContact) -> dict[str, Any]:
    return {
        "id": c.id,
        "phone": c.phone,
        "name": c.name,
        "variables": c.variables,
        "status": c.status,
        "attempts": c.attempts,
        "next_attempt_at": c.next_attempt_at,
        "reason": c.reason,
    }


# --- Exclusion list ----------------------------------------------------------------------------


class ExclusionBody(BaseModel):
    text: str = Field(max_length=importer.MAX_TEXT)


@router.post("/{campaign_id}/exclusions")
async def add_exclusions(
    campaign_id: uuid.UUID, body: ExclusionBody, user: CurrentUser, session: Session
) -> dict[str, Any]:
    """Numbers this campaign must never call (pasted, one per line). Contacts already waiting are
    skipped at once."""
    campaign = await load_campaign(session, user, campaign_id, lock=True)
    try:
        parsed = importer.parse_paste(body.text)
    except importer.MappingError as exc:
        raise HTTPException(422, str(exc)) from exc
    added = await contacts.exclude(session, campaign, [r.phone for r in parsed.rows])
    await session.commit()
    return {"added": added, "invalid_count": len(parsed.invalid)}


@router.get("/{campaign_id}/exclusions")
async def list_exclusions(campaign_id: uuid.UUID, user: CurrentUser, session: Session) -> list[str]:
    campaign = await load_campaign(session, user, campaign_id)
    return list(
        await session.scalars(
            select(CampaignExclusion.phone)
            .where(CampaignExclusion.campaign_id == campaign.id)
            .order_by(CampaignExclusion.phone)
        )
    )


@router.delete("/{campaign_id}/exclusions/{phone}")
async def remove_exclusion(
    campaign_id: uuid.UUID, phone: str, user: CurrentUser, session: Session
) -> dict[str, bool]:
    """Take a number off the list. Contacts skipped because of it stay skipped until retried."""
    campaign = await load_campaign(session, user, campaign_id)
    found = await session.scalar(
        select(CampaignExclusion).where(
            CampaignExclusion.campaign_id == campaign.id, CampaignExclusion.phone == phone
        )
    )
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "that number is not on the list")
    await session.delete(found)
    await session.commit()
    return {"removed": True}
