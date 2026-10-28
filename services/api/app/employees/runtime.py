"""What a call needs to know about an employee, read from its newest published version."""

import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.actions.schema import Action
from app.employees import service
from app.employees.compiler import CallContext, Knowledge, compile_prompt
from app.employees.script import ScriptBundle
from app.models import Account, Employee, EmployeeVersion, Voice
from app.training.knowledge import load as load_knowledge


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
    actions: list[Action] = field(default_factory=list)  # what the AI may do during the call
    party_phone: str | None = None  # the other person's number: the only one a message goes to
    party_name: str | None = None
    has_documents: bool = False  # the AI gets a tool to look things up in them
    max_call_s: int = 600  # the account's call-length cap


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
    knowledge: Knowledge | None = None,
) -> str:
    # What the owner taught applies at once: it is read now, not taken from a published version.
    taught = knowledge or await load_knowledge(session, employee.id)
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
        knowledge=taught,
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
    party_phone: str | None = None,
    party_name: str | None = None,
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
    taught = await load_knowledge(session, employee.id)
    account = await session.get(Account, employee.account_id)
    assert account is not None  # FK guarantees it
    return CallPlan(
        employee_id=employee.id,
        account_id=employee.account_id,
        language=employee.language,
        system_prompt=await prompt_for(
            session, employee, bundle, variables, memory, context, taught
        ),
        voice=await session.get(Voice, employee.voice_id) if employee.voice_id else None,
        tts_speed=settings.tts_speed,
        ambience=settings.ambience,
        ambience_volume=settings.ambience_volume,
        opening=opening,
        transfer_to=transfer_to,
        caller_id=caller_id,
        actions=list(bundle.actions),
        party_phone=party_phone,
        party_name=party_name,
        has_documents=taught.documents,
        max_call_s=account.max_call_s,
    )
