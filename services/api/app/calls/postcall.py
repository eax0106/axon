"""The post-call job: turn each finished call's transcript into data, and act on what it says.

Runs on the worker. The engine leaves a finished call with `analysis_status = 'pending'`; the job
takes pending calls under a row lock (so two workers never analyse the same call), asks the LLM
through the provider registry, and writes the result. Without an LLM key the calls are marked
`skipped`, never filled with made-up data; `reanalyze` puts them back.
"""

import logging
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.calls import analysis
from app.employees import service as employees
from app.instant import rules
from app.instant.rules import DialerSettings
from app.models import (
    Account,
    Call,
    CallEvent,
    CallStatus,
    Direction,
    DncEntry,
    DncSource,
    Employee,
    Lead,
    Notification,
)
from app.providers.base import LLMProvider, ProviderKind, ProviderNotConfiguredError
from app.providers.registry import require

log = logging.getLogger("axon.postcall")
BATCH = 10
STALE_TEST_QUEUED = timedelta(minutes=10)  # a web ticket lives 2 minutes
STALE_TEST_RUNNING = timedelta(minutes=90)  # longer than the longest call (60 minutes)


async def process_pending(
    factory: async_sessionmaker[AsyncSession], now: datetime, *, limit: int = BATCH
) -> int:
    """Analyse pending calls. Returns how many were settled (done, skipped or failed)."""
    llm: LLMProvider | None
    try:
        provider = require(ProviderKind.LLM)
        assert isinstance(provider, LLMProvider)
        llm = provider
    except ProviderNotConfiguredError:
        llm = None
    settled = 0
    async with factory() as session:
        pending = list(
            await session.scalars(
                select(Call)
                .where(Call.analysis_status == "pending")
                .order_by(Call.ended_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        for call in pending:
            await _analyse_one(session, call, llm, now)
            settled += 1
        await session.commit()
    return settled


async def _analyse_one(
    session: AsyncSession, call: Call, llm: LLMProvider | None, now: datetime
) -> None:
    if llm is None:
        call.analysis_status, call.analysis_error = "skipped", "no LLM provider is configured"
        return
    employee = await session.get(Employee, call.employee_id) if call.employee_id else None
    lead = await session.get(Lead, call.lead_id) if call.lead_id else None
    account = await session.get(Account, call.account_id)
    assert account is not None  # FK guarantees it
    capture = employees.settings_of(employee).capture if employee else []
    remember = account.caller_memory and lead is not None
    try:
        result = await analysis.analyse(
            llm,
            call.transcript,
            capture,
            now,
            old_memory=lead.memory if lead else None,
            remember=remember,
        )
    except (analysis.AnalysisError, httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
        call.analysis_status, call.analysis_error = "failed", type(exc).__name__
        log.warning("analysis of call %s failed: %s", call.id, type(exc).__name__)
        return
    call.summary, call.sentiment, call.outcome = result.summary, result.sentiment, result.outcome
    call.captured = {k: v for k, v in result.captured.items() if v is not None}
    call.analysis_status, call.analysis_error = "done", None
    session.add(CallEvent(call_id=call.id, type="analysis_done", data={"outcome": result.outcome}))
    if lead is not None and remember and result.memory:
        lead.memory = result.memory
    if lead is not None and result.do_not_call:
        await _add_to_dnc(session, call, lead)
    elif lead is not None and employee is not None and result.callback_at:
        await _schedule_callback(session, call, lead, employee, result.callback_at)


async def _add_to_dnc(session: AsyncSession, call: Call, lead: Lead) -> None:
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
                reason=f"asked not to be called again (call {call.id})",
            )
        )
        session.add(
            Notification(
                account_id=call.account_id,
                kind="do_not_call_added",
                title="Number added to the do-not-call list",
                body=f"{lead.name or lead.phone} asked not to be called again. "
                "We will not call this number again.",
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
