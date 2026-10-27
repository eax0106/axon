"""Employee operations that touch the database: versions, publish, revert, restore, reset."""

import uuid
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.employees.lifecycle import Action, next_status
from app.employees.script import EmployeeSettings, ScriptBundle
from app.models import (
    Call,
    Employee,
    EmployeeStatus,
    EmployeeVersion,
    KnowledgeDoc,
    KnowledgeItem,
    TrainingSuggestion,
)

KEEP_VERSIONS = 3


async def latest_version(session: AsyncSession, employee_id: uuid.UUID) -> EmployeeVersion | None:
    return await session.scalar(
        select(EmployeeVersion)
        .where(EmployeeVersion.employee_id == employee_id)
        .order_by(EmployeeVersion.version.desc())
        .limit(1)
    )


async def versions(session: AsyncSession, employee_id: uuid.UUID) -> list[EmployeeVersion]:
    rows = await session.scalars(
        select(EmployeeVersion)
        .where(EmployeeVersion.employee_id == employee_id)
        .order_by(EmployeeVersion.version.desc())
    )
    return list(rows)


def bundle_of(employee: Employee) -> ScriptBundle:
    return ScriptBundle.model_validate(employee.draft or {})


def settings_of(employee: Employee) -> EmployeeSettings:
    return EmployeeSettings.model_validate(employee.settings or {})


def has_pending_edits(employee: Employee, live: EmployeeVersion | None) -> bool:
    """True when the draft differs from what live calls use. A never-published employee has none
    to compare, so its whole draft is pending."""
    if live is None:
        return True
    return bundle_of(employee).model_dump() != ScriptBundle.model_validate(live.bundle).model_dump()


async def _add_version(session: AsyncSession, employee: Employee, bundle: dict[str, Any]) -> int:
    """Store `bundle` as the next version, keeping only the newest KEEP_VERSIONS."""
    # Lock the employee row so two publishes cannot take the same version number.
    await session.execute(select(Employee.id).where(Employee.id == employee.id).with_for_update())
    top = await session.scalar(
        select(func.max(EmployeeVersion.version)).where(EmployeeVersion.employee_id == employee.id)
    )
    number = (top or 0) + 1
    session.add(EmployeeVersion(employee_id=employee.id, version=number, bundle=bundle))
    await session.flush()
    await session.execute(
        delete(EmployeeVersion).where(
            EmployeeVersion.employee_id == employee.id,
            EmployeeVersion.version <= number - KEEP_VERSIONS,
        )
    )
    return number


async def publish(session: AsyncSession, employee: Employee) -> int:
    bundle = bundle_of(employee).model_dump()
    number = await _add_version(session, employee, bundle)
    employee.status = next_status(
        employee.status, Action.PUBLISH, has_number=employee.number_id is not None, has_version=True
    )
    await session.commit()
    return number


async def revert(session: AsyncSession, employee: Employee) -> None:
    """Discard pending edits: the draft goes back to the newest published version."""
    live = await latest_version(session, employee.id)
    employee.draft = live.bundle if live else ScriptBundle().model_dump()
    await session.commit()


async def restore(session: AsyncSession, employee: Employee, version: int) -> int | None:
    """Make an old version current again as a new version (so history stays linear and capped)."""
    old = await session.scalar(
        select(EmployeeVersion).where(
            EmployeeVersion.employee_id == employee.id, EmployeeVersion.version == version
        )
    )
    if old is None:
        return None
    number = await _add_version(session, employee, old.bundle)
    employee.draft = old.bundle
    await session.commit()
    return number


async def clear_history(session: AsyncSession, employee: Employee) -> None:
    """Take the employee's calls out of its history. The rows stay: they are the account's billing,
    statement and consent evidence, so they are detached (as deleting an employee does), not
    deleted."""
    await session.execute(
        update(Call).where(Call.employee_id == employee.id).values(employee_id=None)
    )


async def reset(session: AsyncSession, employee: Employee) -> None:
    """Start over: wipe the script, every version, the settings, what it was taught and the call
    history."""
    await session.execute(delete(EmployeeVersion).where(EmployeeVersion.employee_id == employee.id))
    for table in (KnowledgeItem, KnowledgeDoc, TrainingSuggestion):  # passages go with documents
        await session.execute(delete(table).where(table.employee_id == employee.id))
    await clear_history(session, employee)
    employee.draft = ScriptBundle().model_dump()
    employee.settings = EmployeeSettings().model_dump()
    employee.status = EmployeeStatus.DRAFT
    await session.commit()
