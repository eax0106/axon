"""Read an employee's call plan from the database for a call that is starting."""

import uuid

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.employees.runtime import CallPlan, plan_for
from app.models import Call, Employee


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
        is_test = record is not None and record.is_test and record.employee_id == employee_id
        return await plan_for(session, row, use_draft=is_test)
