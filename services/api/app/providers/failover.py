"""Which vendors serve each leg of a call and in what order, and whether a call may start at all.

Every leg (speech-to-text, LLM, text-to-speech) has a chain: the chosen vendor first, then the
other vendors of that kind. A voice tier picks the first text-to-speech vendor; its fallbacks are
the Value and then the Standard vendor, never Premium, so a call can only get cheaper on the way
down. A call is billed at the cheapest tier it used, at the configured rates (`billed_tier`).
The engine builds the chain for each call (unhealthy vendors last) and moves to the next vendor
when one fails mid-call.
"""

import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.config import rate_per_minute
from app.models import Call, CallStatus, Employee, Voice, VoiceTier
from app.providers import health
from app.providers.base import ProviderKind
from app.providers.registry import TIER_TTS, VENDOR_KEYS, missing_keys, selected_name
from app.settings import max_concurrent_calls

LEGS = (ProviderKind.STT, ProviderKind.LLM, ProviderKind.TTS)
LEG_NAMES = {
    ProviderKind.STT: "speech-to-text",
    ProviderKind.LLM: "AI model",
    ProviderKind.TTS: "voice",
}
LIST_ORDER = (VoiceTier.VALUE, VoiceTier.STANDARD, VoiceTier.PREMIUM)  # breaks a tie in rate
FALLBACK_TIERS = (VoiceTier.VALUE, VoiceTier.STANDARD)  # Premium is never a fallback
TTS_TIER = {vendor: tier for tier, vendor in TIER_TTS.items()}
IN_FLIGHT = (CallStatus.RINGING, CallStatus.IN_PROGRESS)

CAPACITY = "the platform is carrying as many calls as it can; calls resume as others end"
CARRIER_DOWN = "the phone carrier is failing right now; calls resume when it recovers"


def chain(kind: ProviderKind, tier: VoiceTier | None = None, first: str | None = None) -> list[str]:
    """The vendors to try for `kind`, in order. `first` (a voice row's own vendor) leads."""
    if kind is ProviderKind.TTS:
        lead = TIER_TTS[tier] if tier is not None else selected_name(kind)
        rest = [TIER_TTS[t] for t in FALLBACK_TIERS]
    else:
        lead, rest = selected_name(kind), list(VENDOR_KEYS[kind])
    vendors = dict.fromkeys(v for v in (first, lead, *rest) if v is not None)
    return [v for v in vendors if v in VENDOR_KEYS[kind]]


def ordered(kind: ProviderKind, vendors: list[str], down: frozenset[tuple[str, str]]) -> list[str]:
    """The same vendors with the unhealthy ones moved to the end (they are still a last resort)."""
    return sorted(vendors, key=lambda v: (str(kind), v) in down)


def billed_tier(tiers: Iterable[VoiceTier | None]) -> VoiceTier | None:
    """The cheapest tier among the voices a call used, at the rates in force: what the minute is
    charged at. A fallback never costs the caller more, whatever the rates are set to."""
    used = [t for t in tiers if t is not None]
    return min(used, key=lambda t: (rate_per_minute(t), LIST_ORDER.index(t))) if used else None


async def employee_voice(session: AsyncSession, employee: Employee) -> Voice | None:
    return await session.get(Voice, employee.voice_id) if employee.voice_id else None


async def in_flight(session: AsyncSession, account_id: uuid.UUID | None = None) -> int:
    query = select(func.count()).where(Call.status.in_(IN_FLIGHT))
    if account_id is not None:
        query = query.where(Call.account_id == account_id)
    return int(await session.scalar(query) or 0)


async def blocked_reason(
    session: AsyncSession, voice: Voice | None, now: datetime, *, outbound: bool = True
) -> str | None:
    """Why the platform may not start a call right now, in plain words, or None. A call is not
    started (it waits) while the platform is full, while the carrier is failing (outbound only),
    or while a leg has no vendor that is both configured and healthy. `voice` is the employee's:
    its vendor leads the voice chain, as on the call itself (`engine.legs.voice_legs`)."""
    if await in_flight(session) >= max_concurrent_calls():
        return CAPACITY
    down = await health.unhealthy(session, now)
    carrier = selected_name(ProviderKind.TELEPHONY)
    if outbound and (str(ProviderKind.TELEPHONY), carrier) in down:
        return CARRIER_DOWN
    tier, own = (voice.tier, voice.provider) if voice else (None, None)
    for kind in LEGS:
        vendors = chain(kind, tier, own if kind is ProviderKind.TTS else None)
        working = [v for v in vendors if not missing_keys(kind, v) and (str(kind), v) not in down]
        if not working:
            return f"no {LEG_NAMES[kind]} provider is working right now; calls resume when one does"
    return None
