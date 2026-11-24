"""The call stack: which vendor and model each AI leg of a call (ears, brain, voice) starts on.

Staff pick it in the admin console; it is stored in `platform_settings` and read by the engine at
the start of every call, so a switch needs no restart. The other vendors of a leg stay behind the
chosen one as failover. Unset, a leg starts on `AXON_<KIND>_PROVIDER` (or the first vendor) with
that vendor's default model, exactly as before. The AI script builder in the API is not affected.
"""

import json
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PlatformSetting
from app.providers.base import ProviderKind
from app.providers.registry import VENDOR_KEYS, selected_name
from app.providers.speech import cartesia, gemini, sarvam, smallest

KEY = "call_stack"
LEGS = (ProviderKind.STT, ProviderKind.LLM, ProviderKind.TTS)

# Models a call may use per vendor; the first is the vendor's default. Only models the engine's
# pipeline service passes through and that the vendor documents are listed.
MODELS: dict[ProviderKind, dict[str, tuple[str, ...]]] = {
    ProviderKind.STT: {
        "sarvam": (sarvam.STT_MODEL,),
        "smallest": ("pulse",),
    },
    ProviderKind.LLM: {
        "gemini": (
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-3.8-flash",
        ),
        # `-conversations` has no hidden reasoning (about 0.2 s to the first word). Plain 105b
        # reasons by default; the engine turns that off with an explicit null (services.py).
        "sarvam": ("sarvam-105b-conversations", sarvam.LLM_MODEL),
    },
    ProviderKind.TTS: {
        "sarvam": (sarvam.TTS_MODEL,),
        "smallest": (smallest.TTS_MODEL,),
        "cartesia": (cartesia.MODEL,),
    },
}


@dataclass(frozen=True)
class Choice:
    vendor: str
    model: str


def default(kind: ProviderKind) -> Choice:
    """What a leg starts on when nothing is saved: the selected vendor at its default model."""
    vendor = selected_name(kind) or next(iter(VENDOR_KEYS[kind]))
    if kind is ProviderKind.LLM and vendor == "gemini":
        return Choice(vendor, gemini.model())  # AXON_GEMINI_MODEL still sets the Gemini default
    return Choice(vendor, MODELS[kind].get(vendor, ("",))[0])


def valid(kind: ProviderKind, choice: Choice) -> bool:
    return choice.model in MODELS[kind].get(choice.vendor, ())


async def load(session: AsyncSession) -> dict[ProviderKind, Choice]:
    """The saved choice per leg. A leg with none (or a stale one, such as a model since removed
    from MODELS) is left out, so the call orders that leg exactly as without a stack."""
    row = await session.get(PlatformSetting, KEY)
    saved = json.loads(row.value) if row else {}
    stack = {}
    for kind in LEGS:
        choice = Choice(*saved.get(str(kind), ["", ""]))
        if valid(kind, choice):
            stack[kind] = choice
    return stack


async def save(session: AsyncSession, stack: dict[ProviderKind, Choice]) -> None:
    value = json.dumps({str(k): [c.vendor, c.model] for k, c in stack.items()})
    row = await session.get(PlatformSetting, KEY)
    if row is None:
        session.add(PlatformSetting(key=KEY, value=value))
    else:
        row.value = value
