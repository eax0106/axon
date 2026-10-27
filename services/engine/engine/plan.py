"""Read an employee's call plan from the database for a call that is starting."""

import uuid

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.employees.runtime import CallPlan, plan_for
from app.inbound.plan import extras
from app.models import Account, Call, CallStatus, CampaignContact, Employee, Lead


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


async def load_plan(db: AsyncEngine, employee: str, call: str = "") -> CallPlan | None:
    """The plan for `employee`: its newest published version, or its draft when `call` is a test
    call (calls.is_test) of that same employee. None if the employee is unknown, or has nothing
    published and this is not a test call. A query string alone never reaches the draft."""
    employee_id = _uuid(employee)
    if employee_id is None:
        return None
    async with async_sessionmaker(db, expire_on_commit=False)() as session:
        row = await session.get(Employee, employee_id)
        if row is None:
            return None
        call_id = _uuid(call) if call else None
        record = await session.get(Call, call_id) if call_id else None
        own = record is not None and record.employee_id == employee_id
        is_test = own and record is not None and record.is_test
        lead = (
            await session.get(Lead, record.lead_id) if own and record and record.lead_id else None
        )
        contact = (
            await session.get(CampaignContact, record.contact_id)
            if own and record and record.contact_id
            else None
        )
        # What the lead source gave us fills the script's variables (and is fenced as data there);
        # a campaign call takes its contact's row of the uploaded list on top.
        variables = (
            {
                "name": (contact.name if contact and contact.name else lead.name) or "",
                **lead.fields,
                **(contact.variables if contact else {}),
            }
            if lead
            else None
        )
        account = await session.get(Account, row.account_id)
        remembered = lead.memory if lead and account and account.caller_memory else None
        added = await extras(session, row, record, lead) if own and record else None
        if added is not None and lead is not None:
            variables = {**(variables or {}), **added.variables}
        return await plan_for(
            session,
            row,
            use_draft=is_test,
            variables=variables,
            memory=remembered,
            context=added.context if added else None,
            opening=added.opening if added else "",
            transfer_to=added.transfer_to if added else None,
            caller_id=added.caller_id if added else None,
            party_phone=(lead.phone if lead else record.caller_phone) if own and record else None,
            party_name=lead.name if lead else None,
        )


async def claim_test_call(db: AsyncEngine, call_id: uuid.UUID, account_id: uuid.UUID) -> bool:
    """Use up a web-call ticket: move its test-call row queued -> in_progress in one statement.
    False when the row is not a queued test call of that account, so a ticket opens one call."""
    async with db.begin() as conn:
        result = await conn.execute(
            update(Call)
            .where(
                Call.id == call_id,
                Call.account_id == account_id,
                Call.is_test.is_(True),
                Call.status == CallStatus.QUEUED,
            )
            .values(status=CallStatus.IN_PROGRESS, started_at=func.now())
        )
        return result.rowcount == 1
