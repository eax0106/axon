"""Which vendors exist per provider kind, which one is selected, and whether its keys are set.

Selection: env `AXON_<KIND>_PROVIDER` (for example `AXON_TTS_PROVIDER=cartesia`), else the first
vendor listed for that kind. A provider is `missing_key` when any of its keys is unset or empty,
`unhealthy` when its adapter is not built yet or its health check fails, and `configured`
only when keys are set and the adapter's health check passes.
"""

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Literal

from app.models import VoiceTier
from app.providers.base import Provider, ProviderKind, ProviderNotConfiguredError
from app.providers.google.sheets import GoogleSheets
from app.providers.leads.meta_lead_ads import MetaLeadAds
from app.providers.speech.cartesia import CartesiaTTS
from app.providers.speech.gemini import GeminiLLM
from app.providers.speech.sarvam import SarvamLLM, SarvamSTT, SarvamTTS
from app.providers.speech.smallest import SmallestSTT, SmallestTTS
from app.providers.telephony.vobiz import VobizTelephony

_VOBIZ = ("VOBIZ_AUTH_ID", "VOBIZ_AUTH_TOKEN")
_GOOGLE = ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET")

# kind -> vendor -> env keys the vendor needs. First vendor is the default.
VENDOR_KEYS: dict[ProviderKind, dict[str, tuple[str, ...]]] = {
    ProviderKind.TELEPHONY: {"vobiz": _VOBIZ},
    ProviderKind.STT: {"sarvam": ("SARVAM_API_KEY",), "smallest": ("SMALLEST_API_KEY",)},
    ProviderKind.LLM: {"gemini": ("GEMINI_API_KEY",), "sarvam": ("SARVAM_API_KEY",)},
    ProviderKind.TTS: {
        "sarvam": ("SARVAM_API_KEY",),
        "smallest": ("SMALLEST_API_KEY",),
        "cartesia": ("CARTESIA_API_KEY",),
    },
    ProviderKind.PAYMENTS: {
        "razorpay": ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET")
    },
    ProviderKind.STORAGE: {
        "r2": ("S3_ENDPOINT_URL", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_BUCKET")
    },
    # ponytail: email vendor is chosen in B6; until then the kind has no vendor to report.
    ProviderKind.EMAIL: {},
    ProviderKind.WHATSAPP: {"interakt": ("INTERAKT_API_KEY",), "aisensy": ("AISENSY_API_KEY",)},
    ProviderKind.CALENDAR: {"google": _GOOGLE},
    ProviderKind.SHEETS: {"google": _GOOGLE},
    ProviderKind.LEADS: {"meta_lead_ads": ("META_APP_ID", "META_APP_SECRET", "META_VERIFY_TOKEN")},
    ProviderKind.NUMBER_KYC: {"vobiz": _VOBIZ},
}

# (kind, vendor) -> adapter class. Each phase adds the real adapters it builds.
ADAPTERS: dict[tuple[ProviderKind, str], type[Provider]] = {
    (ProviderKind.TELEPHONY, "vobiz"): VobizTelephony,
    (ProviderKind.LEADS, "meta_lead_ads"): MetaLeadAds,
    (ProviderKind.SHEETS, "google"): GoogleSheets,
    (ProviderKind.STT, "sarvam"): SarvamSTT,
    (ProviderKind.STT, "smallest"): SmallestSTT,
    (ProviderKind.LLM, "gemini"): GeminiLLM,
    (ProviderKind.LLM, "sarvam"): SarvamLLM,
    (ProviderKind.TTS, "sarvam"): SarvamTTS,
    (ProviderKind.TTS, "smallest"): SmallestTTS,
    (ProviderKind.TTS, "cartesia"): CartesiaTTS,
}

# Voice tier -> TTS vendor (BUILD_PLAN B3). An employee's tier picks its voice vendor per call.
TIER_TTS = {
    VoiceTier.VALUE: "sarvam",
    VoiceTier.STANDARD: "smallest",
    VoiceTier.PREMIUM: "cartesia",
}

Status = Literal["configured", "missing_key", "unhealthy"]
HEALTH_TIMEOUT_S = 5.0
HEALTH_TTL_S = 30.0
# (kind, vendor) -> (monotonic expiry, error or None). Keeps /admin/providers from calling every
# vendor on every request. ponytail: per-process; concurrent misses may both call the vendor.
_health_cache: dict[tuple[ProviderKind, str], tuple[float, str | None]] = {}


@dataclass(frozen=True)
class ProviderReport:
    kind: ProviderKind
    name: str
    selected: bool
    status: Status
    missing_keys: list[str]
    error: str | None = None


def selected_name(kind: ProviderKind) -> str | None:
    vendors = VENDOR_KEYS[kind]
    return os.environ.get(f"AXON_{kind.upper()}_PROVIDER") or next(iter(vendors), None)


def missing_keys(kind: ProviderKind, name: str) -> list[str]:
    return [key for key in VENDOR_KEYS[kind][name] if not os.environ.get(key)]


def resolve(kind: ProviderKind, name: str) -> Provider:
    """The adapter for one vendor, or ProviderNotConfiguredError. Shared by require() and the
    /admin/providers report so both always agree on whether a vendor can be used."""
    missing = missing_keys(kind, name)
    if missing:
        raise ProviderNotConfiguredError(
            kind, name, missing, f"{kind} provider {name!r} needs {', '.join(missing)}"
        )
    adapter = ADAPTERS.get((kind, name))
    if adapter is None:
        raise ProviderNotConfiguredError(kind, name, [], f"{kind} adapter {name!r} not built yet")
    return adapter()


def tts_for_tier(tier: VoiceTier) -> Provider:
    """The TTS adapter for a voice tier, or ProviderNotConfiguredError (served as 503)."""
    return resolve(ProviderKind.TTS, TIER_TTS[tier])


def require(kind: ProviderKind) -> Provider:
    """The selected adapter for `kind`, or ProviderNotConfiguredError (served as 503)."""
    name = selected_name(kind)
    env = f"AXON_{kind.upper()}_PROVIDER"
    if name is None:
        raise ProviderNotConfiguredError(kind, "", [], f"no {kind} vendor chosen yet")
    if name not in VENDOR_KEYS[kind]:
        raise ProviderNotConfiguredError(
            kind, name, [env], f"{env}={name!r} is not a {kind} vendor"
        )
    return resolve(kind, name)


async def _report(kind: ProviderKind, name: str, selected: str | None) -> ProviderReport:
    def row(status: Status, missing: list[str], error: str | None = None) -> ProviderReport:
        return ProviderReport(kind, name, name == selected, status, missing, error)

    try:
        provider = resolve(kind, name)
    except ProviderNotConfiguredError as exc:
        if exc.missing_keys:
            return row("missing_key", exc.missing_keys)
        return row("unhealthy", [], exc.detail)
    error = await _health_error(provider)
    return row("unhealthy", [], error) if error else row("configured", [])


async def _health_error(provider: Provider) -> str | None:
    key, now = (provider.kind, provider.name), time.monotonic()
    cached = _health_cache.get(key)
    if cached and cached[0] > now:
        return cached[1]
    error = None
    try:
        await asyncio.wait_for(provider.health(), HEALTH_TIMEOUT_S)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"[:200]
    _health_cache[key] = (now + HEALTH_TTL_S, error)
    return error


async def report_all() -> list[ProviderReport]:
    checks = [
        _report(kind, name, selected_name(kind))
        for kind, vendors in VENDOR_KEYS.items()
        for name in vendors
    ]
    return list(await asyncio.gather(*checks))
