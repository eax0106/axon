"""Point a number's incoming calls at us.

One voice application per pair of public URLs holds the answer URL (the engine) and the hangup URL
(the API); every number that should be answered is attached to it. The application's id is kept in
`platform_settings` under a key made from the two URLs, so a changed URL gets a new application.
"""

import hashlib
import logging

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.inbound.settings import of as inbound_of
from app.models import Channel, Employee, PhoneNumber, PlatformSetting
from app.providers.base import ProviderKind, ProviderNotConfiguredError, TelephonyProvider
from app.providers.registry import require
from app.settings import api_public_url, engine_public_url

log = logging.getLogger("axon.inbound")


async def application_id(session: AsyncSession, telephony: TelephonyProvider) -> str:
    """The id of our voice application, created the first time it is needed. Does not commit."""
    answer, hangup = f"{engine_public_url()}/vobiz/inbound", f"{api_public_url()}/vobiz/events"
    digest = hashlib.sha256(f"{answer} {hangup}".encode()).hexdigest()
    key = f"voice_app_{digest[:16]}"
    # One creator at a time: two simultaneous first calls would make two applications.
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": key})
    row = await session.get(PlatformSetting, key)
    if row is not None:
        return row.value
    created = await telephony.ensure_application(f"axon-inbound-{digest[:8]}", answer, hangup)
    session.add(PlatformSetting(key=key, value=created))
    await session.flush()
    return created


async def connect(session: AsyncSession, employee: Employee) -> PhoneNumber:
    """Route the employee's number to the application. Needs the carrier keys and public URLs
    (503 otherwise), and a number (409). Does not commit."""
    number = await session.get(PhoneNumber, employee.number_id) if employee.number_id else None
    if number is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "attach a phone number first")
    telephony = require(ProviderKind.TELEPHONY)
    assert isinstance(telephony, TelephonyProvider)
    await telephony.route_number(number.e164, await application_id(session, telephony))
    return number


async def on_activate(session: AsyncSession, employee: Employee) -> None:
    """Called as an employee goes live. An inbound employee cannot work unrouted, so a missing key
    or a carrier error stops the activation; an Instant or Bulk employee that answers its leads'
    call-backs goes live either way (it dials without routing) and the owner can connect later."""
    if employee.channel is Channel.INBOUND:
        await connect(session, employee)
        return
    if not inbound_of(employee.inbound).answer_callbacks:
        return
    try:
        await connect(session, employee)
    except (ProviderNotConfiguredError, HTTPException):
        pass
    except Exception as exc:  # a carrier outage must not keep an outbound employee from going live
        log.warning("could not route %s for call-backs: %s", employee.id, type(exc).__name__)
