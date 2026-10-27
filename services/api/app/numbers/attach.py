"""Which employee uses which number: one number per employee, one employee per number."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Employee, EmployeeStatus, NumberStatus, PhoneNumber

MAX_CHANNELS = 20  # the most calls one number can carry at once (campaign concurrency is 1-20)


async def load_number(
    session: AsyncSession, account_id: uuid.UUID, number_id: uuid.UUID
) -> PhoneNumber:
    """The number, only if it belongs to the account (otherwise 404, never 403)."""
    number = await session.scalar(
        select(PhoneNumber).where(PhoneNumber.id == number_id, PhoneNumber.account_id == account_id)
    )
    if number is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "number not found")
    return number


async def attach(session: AsyncSession, employee: Employee, number_id: uuid.UUID) -> PhoneNumber:
    """Give the employee a number of its own. Does not commit."""
    if employee.number_id is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "this employee already has a number: detach it first"
        )
    number = await load_number(session, employee.account_id, number_id)
    if number.status is not NumberStatus.ACTIVE:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"a {number.status.value} number cannot be attached"
        )
    taken = await session.scalar(select(Employee.id).where(Employee.number_id == number.id))
    if taken is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "this number belongs to another employee")
    employee.number_id = number.id
    return number


async def detach(session: AsyncSession, employee: Employee) -> None:
    """Take the employee's number away; a live employee is paused, since it cannot call
    without one. Does not commit."""
    if employee.number_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "this employee has no number")
    await detach_number(session, employee.number_id)
    await session.refresh(employee)


async def detach_number(session: AsyncSession, number_id: uuid.UUID) -> None:
    """Free a number from whoever holds it (it is being released). Does not commit."""
    await session.execute(
        update(Employee)
        .where(Employee.number_id == number_id, Employee.status == EmployeeStatus.LIVE)
        .values(status=EmployeeStatus.PAUSED)
    )
    await session.execute(
        update(Employee).where(Employee.number_id == number_id).values(number_id=None)
    )
