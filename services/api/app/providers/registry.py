"""Which vendors exist per provider kind, which one is selected, and whether its keys are set.

Selection: env `AXON_<KIND>_PROVIDER` (for example `AXON_TTS_PROVIDER=cartesia`), else the first
vendor listed for that kind. A provider is `missing_key` when any of its keys is unset or empty,
`unhealthy` when its adapter's health check fails, and `configured` otherwise.
"""

import asyncio
import os
from dataclasses import dataclass
from typing import Literal

from app.providers.base import Provider, ProviderKind

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
    ProviderKind.LEADS: {"meta_lead_ads": ("META_APP_SECRET", "META_VERIFY_TOKEN")},
    ProviderKind.NUMBER_KYC: {"vobiz": _VOBIZ},
}

# (kind, vendor) -> adapter class. Filled by the phases that build real adapters.
ADAPTERS: dict[tuple[ProviderKind, str], type[Provider]] = {}

Status = Literal["configured", "missing_key", "unhealthy"]
HEALTH_TIMEOUT_S = 5.0


class ProviderNotConfiguredError(Exception):
    def __init__(self, kind: ProviderKind, name: str, missing_keys: list[str], detail: str):
        super().__init__(detail)
        self.kind, self.name, self.missing_keys, self.detail = kind, name, missing_keys, detail


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
    missing = missing_keys(kind, name)
    if missing:
        raise ProviderNotConfiguredError(
            kind, name, missing, f"{kind} provider {name!r} needs {', '.join(missing)}"
        )
    adapter = ADAPTERS.get((kind, name))
    if adapter is None:
        raise ProviderNotConfiguredError(kind, name, [], f"{kind} adapter {name!r} not built yet")
    return adapter()


async def _report(kind: ProviderKind, name: str, selected: str | None) -> ProviderReport:
    missing = missing_keys(kind, name)
    adapter = ADAPTERS.get((kind, name))
    status: Status = "missing_key" if missing else "configured"
    error = None
    if not missing and adapter is not None:
        try:
            await asyncio.wait_for(adapter().health(), HEALTH_TIMEOUT_S)
        except Exception as exc:
            status, error = "unhealthy", f"{type(exc).__name__}: {exc}"[:200]
    return ProviderReport(kind, name, name == selected, status, missing, error)


async def report_all() -> list[ProviderReport]:
    checks = [
        _report(kind, name, selected_name(kind))
        for kind, vendors in VENDOR_KEYS.items()
        for name in vendors
    ]
    return list(await asyncio.gather(*checks))
