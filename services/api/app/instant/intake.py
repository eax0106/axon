"""Turn something a lead source sent into a lead and a queued call, or say why not.

Every outcome is written to the intake log (accepted / deduplicated / rejected), including
rejections, so the owner can see exactly what each source delivered and what became of it.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.employees import service as employees
from app.employees.compiler import clean_value
from app.instant import rules
from app.instant.rules import DialerSettings
from app.models import (
    Call,
    CallStatus,
    Channel,
    Direction,
    DncEntry,
    Employee,
    EmployeeStatus,
    IntakeStatus,
    Lead,
    LeadIntakeEntry,
)

INDIA_MOBILE = re.compile(r"^(?:\+?91)?([6-9]\d{9})$")
PHONE_KEYS = ("phone", "phone_number", "mobile", "mobile_number", "contact_number")
NAME_KEYS = ("name", "full_name", "first_name")


def normalize_phone(raw: object) -> str | None:
    """+91XXXXXXXXXX for an Indian mobile number written the usual ways, else None."""
    text = re.sub(r"[\s\-().]", "", str(raw or ""))
    match = INDIA_MOBILE.match(text)
    return f"+91{match.group(1)}" if match else None


def key_of(raw: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", raw.strip().lower()).strip("_")


def pick(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    by_key = {key_of(str(k)): v for k, v in payload.items()}
    for key in keys:
        if by_key.get(key) not in (None, ""):
            return clean_value(by_key[key])
    return None


def map_fields(payload: dict[str, Any], declared: list[str]) -> dict[str, str]:
    """Only the employee's declared pre-call variables are kept; everything else is ignored."""
    by_key = {key_of(str(k)): v for k, v in payload.items() if v not in (None, "")}
    return {name: clean_value(by_key[name]) for name in declared if name in by_key}


@dataclass
class Result:
    status: IntakeStatus
    reason: str | None = None
    lead_id: Any = None
    call_id: Any = None
    scheduled_for: datetime | None = None
    variables: dict[str, str] = field(default_factory=dict)


async def process(
    session: AsyncSession,
    employee: Employee,
    payload: dict[str, Any],
    *,
    source: str,
    now: datetime,
    dry_run: bool = False,
    dedupe: bool = True,
) -> Result:
    """Run one lead through the rules. `dry_run` (test leads) decides and logs but creates no lead
    and no call. Commits."""
    settings = DialerSettings.model_validate(employee.dialer or {})
    declared = employees.bundle_of(employee).pre_call_variables
    phone = normalize_phone(pick(payload, PHONE_KEYS))
    if phone is not None:
        # One lead at a time per employee and number, so two posts of the same lead (Zapier and n8n
        # retry) cannot both pass the duplicate check or both create the lead.
        await session.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(f"{employee.id}:{phone}", 0)))
        )
    result = await _decide(session, employee, settings, phone, now, dry_run, dedupe)
    if result.status is IntakeStatus.ACCEPTED:
        result.variables = map_fields(payload, declared)
        name = pick(payload, NAME_KEYS)
        assert phone is not None
        if not dry_run:
            lead = await _upsert_lead(session, employee, phone, name, result.variables)
            result.lead_id = lead.id
            at = rules.first_attempt_time(now, settings, rules.IST)
            call = Call(
                account_id=employee.account_id,
                employee_id=employee.id,
                lead_id=lead.id,
                direction=Direction.OUTBOUND,
                channel=Channel.INSTANT,
                status=CallStatus.QUEUED,
                scheduled_for=at,
                attempt=1,
            )
            session.add(call)
            await session.flush()
            result.call_id, result.scheduled_for = call.id, at
    session.add(
        LeadIntakeEntry(
            account_id=employee.account_id,
            employee_id=employee.id,
            source="test" if dry_run else source,
            status=result.status,
            reason=result.reason,
            phone=phone,
            lead_id=result.lead_id,
            call_id=result.call_id,
            created_at=now,
        )
    )
    await session.commit()
    return result


async def _decide(
    session: AsyncSession,
    employee: Employee,
    settings: DialerSettings,
    phone: str | None,
    now: datetime,
    dry_run: bool,
    dedupe: bool,
) -> Result:
    if employee.channel is not Channel.INSTANT:
        return Result(IntakeStatus.REJECTED, "this employee is not on the Instant channel")
    if employee.status is not EmployeeStatus.LIVE and not dry_run:
        return Result(IntakeStatus.REJECTED, "employee is not live")
    if phone is None:
        return Result(IntakeStatus.REJECTED, "no valid Indian mobile number")
    on_dnc = await session.scalar(
        select(DncEntry.id).where(
            DncEntry.account_id == employee.account_id, DncEntry.phone == phone
        )
    )
    if on_dnc:
        return Result(IntakeStatus.REJECTED, "number is on the do-not-call list")
    if dedupe and settings.dedup_recent_days:
        since = now - timedelta(days=settings.dedup_recent_days)
        seen = await session.scalar(
            select(LeadIntakeEntry.id)
            .where(
                LeadIntakeEntry.employee_id == employee.id,
                LeadIntakeEntry.phone == phone,
                LeadIntakeEntry.status == IntakeStatus.ACCEPTED,
                LeadIntakeEntry.source != "test",
                LeadIntakeEntry.created_at > since,
            )
            .limit(1)
        )
        if seen:
            return Result(
                IntakeStatus.DEDUPLICATED,
                f"already received in the last {settings.dedup_recent_days} day(s)",
            )
    return Result(IntakeStatus.ACCEPTED)


async def _upsert_lead(
    session: AsyncSession,
    employee: Employee,
    phone: str,
    name: str | None,
    variables: dict[str, str],
) -> Lead:
    lead = await session.scalar(
        select(Lead).where(Lead.account_id == employee.account_id, Lead.phone == phone)
    )
    if lead is None:
        lead = Lead(account_id=employee.account_id, phone=phone, name=name, fields=variables)
        session.add(lead)
    else:
        lead.name = name or lead.name
        lead.fields = {**lead.fields, **variables}
    await session.flush()
    return lead
