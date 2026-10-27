"""The post-call job: turn each finished call's transcript into data, and act on what it says.

Runs on the worker. The engine leaves a finished call with `analysis_status = 'pending'`; the job
takes pending calls under a row lock (so two workers never analyse the same call), asks the LLM
through the provider registry, and writes the result. Without an LLM key the calls are marked
`skipped`, never filled with made-up data; `reanalyze` puts them back.
"""

import logging
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.billing.fees import charge_ai_use
from app.calls import analysis
from app.campaigns import contacts as campaign_contacts
from app.employees import service as employees
from app.inbound import messages
from app.instant import rules
from app.instant.rules import DialerSettings
from app.models import (
    Account,
    Call,
    CallEvent,
    CallStatus,
    Channel,
    Direction,
    DncEntry,
    DncSource,
    Employee,
    Lead,
    Notification,
)
from app.providers.base import LLMProvider, ProviderKind, ProviderNotConfiguredError
from app.providers.registry import require
from app.training import struggle

log = logging.getLogger("axon.postcall")
BATCH = 3  # a batch must finish inside the worker's job timeout: 3 x 60 s of LLM
CLAIM_TIMEOUT = timedelta(minutes=10)  # an `analysing` claim older than this was abandoned
STALE_TEST_QUEUED = timedelta(minutes=10)  # a web ticket lives 2 minutes
STALE_TEST_RUNNING = timedelta(minutes=90)  # longer than the longest call (60 minutes)


async def process_pending(
    factory: async_sessionmaker[AsyncSession], now: datetime, *, limit: int = BATCH
) -> int:
    """Analyse pending calls. Returns how many were taken (done, skipped or failed).

    Each call is claimed (marked `analysing`, committed) so no lock is held while the LLM works,
    then analysed and written in its own transaction; one bad call never rolls back the others."""
    llm: LLMProvider | None
    try:
        provider = require(ProviderKind.LLM)
        assert isinstance(provider, LLMProvider)
        llm = provider
    except ProviderNotConfiguredError:
        llm = None
    claimed = await _claim(factory, now, limit, skip=llm is None)
    if llm is not None:
        for call_id in claimed:
            await _run_one(factory, call_id, llm, now)
    return len(claimed)


async def _claim(
    factory: async_sessionmaker[AsyncSession], now: datetime, limit: int, *, skip: bool
) -> list[Any]:
    """Pending calls (and ones another worker claimed long ago and never finished), oldest first,
    taken under `SKIP LOCKED` so two workers never get the same call."""
    async with factory() as session:
        rows = list(
            await session.scalars(
                select(Call)
                .where(
                    or_(
                        Call.analysis_status == "pending",
                        and_(
                            Call.analysis_status == "analysing",
                            Call.analysis_started_at < now - CLAIM_TIMEOUT,
                        ),
                    )
                )
                .order_by(Call.ended_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        for call in rows:
            if skip:
                call.analysis_status, call.analysis_error = (
                    "skipped",
                    "no LLM provider is configured",
                )
            else:
                call.analysis_status, call.analysis_started_at = "analysing", now
        await session.commit()
        return [call.id for call in rows]


async def _run_one(
    factory: async_sessionmaker[AsyncSession], call_id: Any, llm: LLMProvider, now: datetime
) -> None:
    try:
        async with factory() as session:  # read what the model needs; no lock is kept
            call = await session.get(Call, call_id)
            if call is None or call.analysis_status != "analysing":
                return
            employee = await session.get(Employee, call.employee_id) if call.employee_id else None
            lead = await session.get(Lead, call.lead_id) if call.lead_id else None
            account = await session.get(Account, call.account_id)
            assert account is not None  # FK guarantees it
            turns = list(call.transcript)
            capture = employees.settings_of(employee).capture if employee else []
            remember = account.caller_memory and lead is not None
            old_memory = lead.memory if lead else None
        try:
            result = await analysis.analyse(
                llm, turns, capture, now, old_memory=old_memory, remember=remember
            )
        except (analysis.AnalysisError, httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            await _mark_failed(factory, call_id, type(exc).__name__)
            return
        async with factory() as session:  # write the result; the call row is locked only now
            call = await session.get(Call, call_id, with_for_update=True)
            if call is None or call.analysis_status != "analysing":
                return
            await _apply(session, call, result, remember, now)
            await session.commit()
    except Exception as exc:  # a poison pill: this call fails, the rest of the batch goes on
        log.exception("analysis of call %s crashed", call_id)
        await _mark_failed(factory, call_id, type(exc).__name__)


async def _mark_failed(factory: async_sessionmaker[AsyncSession], call_id: Any, error: str) -> None:
    log.warning("analysis of call %s failed: %s", call_id, error)
    async with factory() as session:
        await session.execute(
            update(Call)
            .where(Call.id == call_id, Call.analysis_status == "analysing")
            .values(analysis_status="failed", analysis_error=error[:200])
        )
        await session.commit()


async def _apply(
    session: AsyncSession, call: Call, result: analysis.Analysis, remember: bool, now: datetime
) -> None:
    employee = await session.get(Employee, call.employee_id) if call.employee_id else None
    lead = await session.get(Lead, call.lead_id) if call.lead_id else None
    call.summary, call.sentiment, call.outcome = result.summary, result.sentiment, result.outcome
    call.captured = {k: v for k, v in result.captured.items() if v is not None}
    call.analysis_status, call.analysis_error = "done", None
    # The work is done, so the fee is taken even if it leaves the account at zero. Once per call:
    # only a skipped or failed analysis can be run again, and that never reached this line.
    await charge_ai_use(session, call.account_id, "analysis", str(call.id), allow_overdraw=True)
    session.add(CallEvent(call_id=call.id, type="analysis_done", data={"outcome": result.outcome}))
    if lead is not None and remember and result.memory:
        lead.memory = result.memory
    if lead is not None and result.do_not_call:
        await _add_to_dnc(session, call, lead, result.do_not_call_quote)
    elif (
        lead is not None
        and employee is not None
        and result.callback_at
        and not _rung_in(call, employee)
    ):
        await _schedule_callback(session, call, lead, employee, result.callback_at)
    if call.direction is Direction.INBOUND and not result.do_not_call:
        await _take_message(session, call, lead, result, now)
    if employee is not None:
        await struggle.store(session, call, employee, result.struggles)


def _rung_in(call: Call, employee: Employee) -> bool:
    """A Bulk employee's incoming call: nothing dials a Bulk employee's own call-back (its
    campaign calls its contacts), so no call is queued; the message task covers the request."""
    return call.direction is Direction.INBOUND and employee.channel is Channel.BULK


async def _take_message(
    session: AsyncSession, call: Call, lead: Lead | None, result: analysis.Analysis, now: datetime
) -> None:
    """A message or call-back request from an incoming call becomes a task for the owner."""
    body = result.message
    if body is None and result.callback_at is not None:
        asked = result.callback_at.astimezone(analysis.IST).strftime("%d %b, %H:%M")
        body = f"Asked to be called back: {asked} IST."
    if body is not None:
        await messages.add(session, call, body, result.callback_at, lead, now)


async def _add_to_dnc(session: AsyncSession, call: Call, lead: Lead, quote: str | None) -> None:
    exists = await session.scalar(
        select(DncEntry.id).where(
            DncEntry.account_id == call.account_id, DncEntry.phone == lead.phone
        )
    )
    if not exists:
        session.add(
            DncEntry(
                account_id=call.account_id,
                phone=lead.phone,
                source=DncSource.CALLER_REQUEST,
                reason=f'asked not to be called again: "{quote}" (call {call.id})'[:500],
            )
        )
        session.add(
            Notification(
                account_id=call.account_id,
                kind="do_not_call_added",
                title="Number added to the do-not-call list",
                body=f'{lead.name or lead.phone} said: "{quote}". We will not call this number '
                "again. If this is a mistake, remove the number from the do-not-call list.",
            )
        )
    # Nothing already waiting for this number may still ring.
    await session.execute(
        update(Call)
        .where(
            Call.account_id == call.account_id,
            Call.lead_id == lead.id,
            Call.status == CallStatus.QUEUED,
        )
        .values(status=CallStatus.CANCELED)
    )
    session.add(CallEvent(call_id=call.id, type="do_not_call", data={}))


async def _schedule_callback(
    session: AsyncSession, call: Call, lead: Lead, employee: Employee, asked_for: datetime
) -> None:
    if call.campaign_id is not None:  # a campaign's contact is called back by its campaign
        await campaign_contacts.callback(session, call, lead, asked_for)
        return
    waiting = await session.scalar(
        select(Call.id).where(
            Call.employee_id == employee.id,
            Call.lead_id == lead.id,
            Call.status == CallStatus.QUEUED,
            Call.is_callback.is_(True),
        )
    )
    if waiting:
        return  # one callback at a time; the caller's latest wish is not guessed over
    settings = DialerSettings.model_validate(employee.dialer or {})
    at = rules.next_window_start(asked_for, settings, rules.IST)  # never outside calling hours
    session.add(
        Call(
            account_id=call.account_id,
            employee_id=employee.id,
            lead_id=lead.id,
            direction=Direction.OUTBOUND,
            channel=call.channel,
            status=CallStatus.QUEUED,
            scheduled_for=at,
            attempt=1,
            is_callback=True,
        )
    )
    local = at.astimezone(analysis.IST).strftime("%d %b, %H:%M")
    session.add(
        Notification(
            account_id=call.account_id,
            kind="callback_scheduled",
            title="Callback scheduled",
            body=f"{lead.name or lead.phone} asked to be called back: {local} IST.",
        )
    )
    session.add(CallEvent(call_id=call.id, type="callback_scheduled", data={"at": at.isoformat()}))


async def reanalyze(session: AsyncSession, call: Call) -> bool:
    """Put a skipped or failed call back in the queue. False if there is nothing to analyse."""
    if call.analysis_status not in ("skipped", "failed") or not call.transcript:
        return False
    call.analysis_status, call.analysis_error = "pending", None
    return True


async def reap_test_calls(factory: async_sessionmaker[AsyncSession], now: datetime) -> int:
    """Test calls (phone and browser) that never finished must not sit in `queued` or
    `in_progress` forever: a web ticket nobody used, or a claimed call whose setup failed."""
    async with factory() as session:
        unused = await session.execute(
            update(Call)
            .where(
                Call.is_test.is_(True),
                Call.status == CallStatus.QUEUED,
                Call.created_at < now - STALE_TEST_QUEUED,
            )
            .values(status=CallStatus.CANCELED)
        )
        stuck = await session.execute(
            update(Call)
            .where(
                Call.is_test.is_(True),
                Call.status == CallStatus.IN_PROGRESS,
                Call.started_at < now - STALE_TEST_RUNNING,
            )
            .values(status=CallStatus.FAILED, ended_at=now)
        )
        await session.commit()
    return int(unused.rowcount or 0) + int(stuck.rowcount or 0)  # type: ignore[attr-defined]
