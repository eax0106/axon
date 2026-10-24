"""Employee endpoints, all scoped to the caller's account."""

import hashlib
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentUser
from app.db import Session
from app.employees import runtime, service
from app.employees.lifecycle import Action, TransitionError, next_status
from app.employees.script import LANGUAGES, EmployeeSettings, ScriptBundle
from app.models import Channel, Employee, EmployeeStatus, Purpose, Role, User, Voice, VoiceTier
from app.voices import VoiceOut, default_voice, supports, voice_out

router = APIRouter(prefix="/employees")

# What an employee is for, by channel, when the caller does not say (DECISIONS: purpose rule table).
DEFAULT_PURPOSE = {
    Channel.INSTANT: Purpose.SERVICE,
    Channel.BULK: Purpose.PROMOTIONAL,
    Channel.INBOUND: Purpose.SERVICE,
}


async def owner_only(user: CurrentUser) -> User:
    if user.role is not Role.OWNER:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only the account owner can do this")
    return user


OwnerUser = Annotated[User, Depends(owner_only)]


async def load(session: AsyncSession, user: User, employee_id: uuid.UUID) -> Employee:
    """The employee, only if it belongs to the caller's account (otherwise 404, never 403)."""
    employee = await session.scalar(
        select(Employee).where(Employee.id == employee_id, Employee.account_id == user.account_id)
    )
    if employee is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "employee not found")
    return employee


def _languages(language: str, extra: list[str]) -> None:
    unknown = [x for x in [language, *extra] if x not in LANGUAGES]
    if unknown:
        raise HTTPException(422, f"unsupported language {unknown[0]!r}; use {', '.join(LANGUAGES)}")
    if language in extra or len(set(extra)) != len(extra):
        raise HTTPException(422, "extra_languages must be distinct and exclude the main language")


async def _check_voice(session: AsyncSession, voice_id: uuid.UUID, languages: list[str]) -> Voice:
    voice = await session.get(Voice, voice_id)
    if voice is None:
        raise HTTPException(422, "unknown voice")
    if not supports(voice, languages):
        raise HTTPException(
            422, f"voice {voice.public_name!r} does not speak every language chosen"
        )
    return voice


class EmployeeCreate(BaseModel):
    name: str = Field("New employee", min_length=1, max_length=100)
    role_title: str | None = Field(None, max_length=200)
    channel: Channel
    purpose: Purpose | None = None
    language: str = "en"
    extra_languages: list[str] = []
    voice_id: uuid.UUID | None = None


class EmployeeUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    role_title: str | None = Field(None, max_length=200)
    purpose: Purpose | None = None
    language: str | None = None
    extra_languages: list[str] | None = None
    voice_id: uuid.UUID | None = None

    @field_validator("name", "language", "extra_languages", "purpose")
    @classmethod
    def _not_null(cls, value: Any) -> Any:
        return value  # None means "leave unchanged"; present values are validated in the handler


class EmployeeOut(BaseModel):
    id: uuid.UUID
    name: str
    role_title: str | None
    channel: Channel
    purpose: Purpose
    status: EmployeeStatus
    language: str
    extra_languages: list[str]
    voice: VoiceOut | None
    number_id: uuid.UUID | None
    published_version: int | None
    has_pending_edits: bool
    avatar: dict[str, Any]
    script: ScriptBundle
    settings: EmployeeSettings


def avatar(employee: Employee) -> dict[str, Any]:
    """A stable placeholder avatar: initials and a hue derived from the id."""
    words = employee.name.split()
    initials = "".join(w[0] for w in words[:2]).upper() or "?"
    hue = int(hashlib.sha256(employee.id.bytes).hexdigest()[:4], 16) % 360
    return {"initials": initials, "hue": hue}


async def out(session: AsyncSession, employee: Employee) -> EmployeeOut:
    live = await service.latest_version(session, employee.id)
    voice = await session.get(Voice, employee.voice_id) if employee.voice_id else None
    return EmployeeOut(
        id=employee.id,
        name=employee.name,
        role_title=employee.role_title,
        channel=employee.channel,
        purpose=employee.purpose,
        status=employee.status,
        language=employee.language,
        extra_languages=employee.extra_languages,
        voice=voice_out(voice) if voice else None,
        number_id=employee.number_id,
        published_version=live.version if live else None,
        has_pending_edits=service.has_pending_edits(employee, live),
        avatar=avatar(employee),
        script=service.bundle_of(employee),
        settings=service.settings_of(employee),
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(body: EmployeeCreate, user: CurrentUser, session: Session) -> EmployeeOut:
    _languages(body.language, body.extra_languages)
    if body.voice_id:
        voice = await _check_voice(session, body.voice_id, [body.language, *body.extra_languages])
    else:
        found = await default_voice(session, body.language, VoiceTier.VALUE)
        if found is None:
            raise HTTPException(409, f"no voice for language {body.language!r} in the catalog")
        voice = found
    employee = Employee(
        account_id=user.account_id,
        name=body.name,
        role_title=body.role_title,
        channel=body.channel,
        purpose=body.purpose or DEFAULT_PURPOSE[body.channel],
        status=EmployeeStatus.DRAFT,
        language=body.language,
        extra_languages=body.extra_languages,
        voice_id=voice.id,
        draft=ScriptBundle().model_dump(),
        settings=EmployeeSettings().model_dump(),
    )
    session.add(employee)
    await session.commit()
    return await out(session, employee)


@router.get("")
async def list_employees(user: CurrentUser, session: Session) -> list[EmployeeOut]:
    rows = await session.scalars(
        select(Employee).where(Employee.account_id == user.account_id).order_by(Employee.created_at)
    )
    return [await out(session, e) for e in rows]


@router.get("/{employee_id}")
async def get_employee(employee_id: uuid.UUID, user: CurrentUser, session: Session) -> EmployeeOut:
    return await out(session, await load(session, user, employee_id))


@router.patch("/{employee_id}")
async def update(
    employee_id: uuid.UUID, body: EmployeeUpdate, user: CurrentUser, session: Session
) -> EmployeeOut:
    employee = await load(session, user, employee_id)
    fields = body.model_dump(exclude_unset=True)
    for key in ("name", "language", "extra_languages", "purpose"):
        if key in fields and fields[key] is None:
            raise HTTPException(422, f"{key} cannot be null")
    language = fields.get("language", employee.language)
    extra = fields.get("extra_languages", employee.extra_languages)
    _languages(language, extra)
    voice_id = fields.get("voice_id", employee.voice_id)
    if voice_id:
        await _check_voice(session, voice_id, [language, *extra])
    elif "voice_id" in fields:
        raise HTTPException(422, "an employee needs a voice")
    for key, value in fields.items():
        setattr(employee, key, value)
    await session.commit()
    return await out(session, employee)


@router.delete("/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(employee_id: uuid.UUID, user: OwnerUser, session: Session) -> None:
    await session.delete(await load(session, user, employee_id))
    await session.commit()


@router.post("/{employee_id}/duplicate", status_code=status.HTTP_201_CREATED)
async def duplicate(employee_id: uuid.UUID, user: CurrentUser, session: Session) -> EmployeeOut:
    source = await load(session, user, employee_id)
    copy = Employee(
        account_id=source.account_id,
        name=f"{source.name} (copy)"[:100],
        role_title=source.role_title,
        channel=source.channel,
        purpose=source.purpose,
        status=EmployeeStatus.DRAFT,
        language=source.language,
        extra_languages=list(source.extra_languages),
        voice_id=source.voice_id,
        draft=source.draft,
        settings=source.settings,
    )
    session.add(copy)
    await session.commit()
    return await out(session, copy)


@router.put("/{employee_id}/script")
async def put_script(
    employee_id: uuid.UUID, body: ScriptBundle, user: CurrentUser, session: Session
) -> EmployeeOut:
    """Replace the draft script. It reaches live calls only after publish."""
    employee = await load(session, user, employee_id)
    employee.draft = body.model_dump()
    await session.commit()
    return await out(session, employee)


@router.put("/{employee_id}/settings")
async def put_settings(
    employee_id: uuid.UUID, body: EmployeeSettings, user: CurrentUser, session: Session
) -> EmployeeOut:
    """Voice speed, ambience, toggles and capture fields: these apply to live calls at once."""
    employee = await load(session, user, employee_id)
    employee.settings = body.model_dump()
    await session.commit()
    return await out(session, employee)


@router.get("/{employee_id}/prompt")
async def preview_prompt(
    employee_id: uuid.UUID,
    user: CurrentUser,
    session: Session,
    source: Annotated[Literal["draft", "live"], Query()] = "draft",
) -> dict[str, str]:
    """The exact system prompt a call would run on, for the draft or the live version."""
    employee = await load(session, user, employee_id)
    if source == "live":
        live = await service.latest_version(session, employee.id)
        if live is None:
            raise HTTPException(409, "nothing is published yet")
        bundle = ScriptBundle.model_validate(live.bundle)
    else:
        bundle = service.bundle_of(employee)
    return {"prompt": await runtime.prompt_for(session, employee, bundle)}


@router.post("/{employee_id}/publish")
async def publish(employee_id: uuid.UUID, user: CurrentUser, session: Session) -> EmployeeOut:
    employee = await load(session, user, employee_id)
    await service.publish(session, employee)
    return await out(session, employee)


@router.post("/{employee_id}/revert")
async def revert(employee_id: uuid.UUID, user: CurrentUser, session: Session) -> EmployeeOut:
    """Discard pending edits."""
    employee = await load(session, user, employee_id)
    await service.revert(session, employee)
    return await out(session, employee)


class VersionOut(BaseModel):
    version: int
    published_at: str
    script: ScriptBundle


@router.get("/{employee_id}/versions")
async def list_versions(
    employee_id: uuid.UUID, user: CurrentUser, session: Session
) -> list[VersionOut]:
    employee = await load(session, user, employee_id)
    return [
        VersionOut(
            version=v.version,
            published_at=v.published_at.isoformat(),
            script=ScriptBundle.model_validate(v.bundle),
        )
        for v in await service.versions(session, employee.id)
    ]


@router.post("/{employee_id}/versions/{version}/restore")
async def restore(
    employee_id: uuid.UUID, version: int, user: CurrentUser, session: Session
) -> EmployeeOut:
    employee = await load(session, user, employee_id)
    if await service.restore(session, employee, version) is None:
        raise HTTPException(404, "version not found (only the last 3 are kept)")
    return await out(session, employee)


async def _move(session: AsyncSession, employee: Employee, action: Action) -> EmployeeOut:
    live = await service.latest_version(session, employee.id)
    try:
        employee.status = next_status(
            employee.status,
            action,
            has_number=employee.number_id is not None,
            has_version=live is not None,
        )
    except TransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await session.commit()
    return await out(session, employee)


@router.post("/{employee_id}/activate")
async def activate(employee_id: uuid.UUID, user: OwnerUser, session: Session) -> EmployeeOut:
    return await _move(session, await load(session, user, employee_id), Action.ACTIVATE)


@router.post("/{employee_id}/deactivate")
async def deactivate(employee_id: uuid.UUID, user: OwnerUser, session: Session) -> EmployeeOut:
    return await _move(session, await load(session, user, employee_id), Action.DEACTIVATE)


class SwitchMode(BaseModel):
    channel: Channel


@router.post("/{employee_id}/switch-mode")
async def switch_mode(
    employee_id: uuid.UUID, body: SwitchMode, user: OwnerUser, session: Session
) -> dict[str, Any]:
    """Change channel. Call history belongs to the old channel, so it is cleared; a live employee
    is paused until it is activated again. The script is kept and a rewrite is offered."""
    employee = await load(session, user, employee_id)
    if body.channel is employee.channel:
        raise HTTPException(409, "already on that channel")
    await service.clear_history(session, employee)
    employee.channel = body.channel
    employee.purpose = DEFAULT_PURPOSE[body.channel]
    if employee.status is EmployeeStatus.LIVE:
        employee.status = EmployeeStatus.PAUSED
    await session.commit()
    return {"employee": await out(session, employee), "rewrite_offered": True}


@router.post("/{employee_id}/reset")
async def reset(employee_id: uuid.UUID, user: OwnerUser, session: Session) -> EmployeeOut:
    """Start over: wipes the script, versions, settings and call history."""
    employee = await load(session, user, employee_id)
    await service.reset(session, employee)
    return await out(session, employee)
