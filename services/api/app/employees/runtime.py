"""What a call needs to know about an employee, read from its newest published version."""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.employees import service
from app.employees.compiler import CallContext, compile_prompt
from app.employees.script import ScriptBundle
from app.models import Account, Employee, EmployeeVersion, Voice


@dataclass(frozen=True)
class CallPlan:
    employee_id: uuid.UUID
    account_id: uuid.UUID
    language: str
    system_prompt: str
    voice: Voice | None
    tts_speed: float
    ambience: str
    ambience_volume: float
    opening: str = ""  # spoken before the caller says anything (incoming calls)
    transfer_to: str | None = None  # a person the AI may hand the call to
    caller_id: str | None = None  # the number the transfer leg shows: the employee's own


async def business_name(session: AsyncSession, employee: Employee) -> str:
    account = await session.get(Account, employee.account_id)
    assert account is not None  # FK guarantees it
    return account.business_name or account.name


async def prompt_for(
    session: AsyncSession,
    employee: Employee,
    bundle: ScriptBundle,
    variables: dict[str, str] | None = None,
    memory: str | None = None,
    context: CallContext | None = None,
) -> str:
    return compile_prompt(
        name=employee.name,
        role_title=employee.role_title,
        business_name=await business_name(session, employee),
        language=employee.language,
        extra_languages=employee.extra_languages,
        bundle=bundle,
        settings=service.settings_of(employee),
        variables=variables,
        memory=memory,
        context=context,
    )


async def plan_for(
    session: AsyncSession,
    employee: Employee,
    *,
    version: EmployeeVersion | None = None,
    use_draft: bool = False,
    variables: dict[str, str] | None = None,
    memory: str | None = None,
    context: CallContext | None = None,
    opening: str = "",
    transfer_to: str | None = None,
    caller_id: str | None = None,
) -> CallPlan | None:
    """The plan for a call: the newest published version, or the draft for test calls.
    None when there is nothing published and no draft was asked for."""
    if use_draft:
        bundle = service.bundle_of(employee)
    else:
        live = version or await service.latest_version(session, employee.id)
        if live is None:
            return None
        bundle = ScriptBundle.model_validate(live.bundle)
    settings = service.settings_of(employee)
    return CallPlan(
        employee_id=employee.id,
        account_id=employee.account_id,
        language=employee.language,
        system_prompt=await prompt_for(session, employee, bundle, variables, memory, context),
        voice=await session.get(Voice, employee.voice_id) if employee.voice_id else None,
        tts_speed=settings.tts_speed,
        ambience=settings.ambience,
        ambience_volume=settings.ambience_volume,
        opening=opening,
        transfer_to=transfer_to,
        caller_id=caller_id,
    )
