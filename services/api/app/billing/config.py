"""Prices and tax settings. Every figure here is business configuration, not logic: change the
environment variable and nothing else. Defaults are the launch prices and are for the owner to
confirm (docs/phases/b7.md lists them).

Money is `Decimal` rupees; one credit is one rupee, kept to four decimals so a second of talk can
be billed exactly.
"""

import os
from decimal import Decimal

from app.models import VoiceTier

CREDIT_DECIMALS = Decimal("0.0001")


def _money(name: str, default: str) -> Decimal:
    return Decimal(os.environ.get(name) or default)


def rate_per_minute(tier: VoiceTier | str) -> Decimal:
    """Rupees per minute of talk time, by voice tier."""
    key = VoiceTier(tier)
    defaults = {VoiceTier.VALUE: "3.5", VoiceTier.STANDARD: "5", VoiceTier.PREMIUM: "7"}
    return _money(f"AXON_RATE_{key.name}_PER_MIN", defaults[key])


def ai_use_fee() -> Decimal:
    """Rupees for each use of AI help (builder, chat sandbox, voice preview, analysis)."""
    return _money("AXON_AI_USE_FEE", "0.2")


def free_signup_credits() -> Decimal:
    return _money("AXON_FREE_CREDITS", "50")


def number_monthly_fee() -> Decimal:
    return _money("AXON_NUMBER_MONTHLY_FEE", "649")


def extra_channel_monthly_fee() -> Decimal:
    return _money("AXON_EXTRA_CHANNEL_FEE", "0")


def low_balance_threshold() -> Decimal:
    return _money("AXON_LOW_BALANCE", "50")


def grace_days() -> int:
    return int(os.environ.get("AXON_NUMBER_GRACE_DAYS") or "7")


def gst_rate_percent() -> Decimal:
    """GST percent on what customers pay. Config, because the right rate and code are the
    business's tax advisor's to say."""
    return _money("AXON_GST_RATE", "18")


def gst_sac_code() -> str:
    return os.environ.get("AXON_GST_SAC", "")


def seller_details() -> dict[str, str]:
    return {
        "legal_name": os.environ.get("AXON_SELLER_NAME", ""),
        "gstin": os.environ.get("AXON_SELLER_GSTIN", ""),
        "address": os.environ.get("AXON_SELLER_ADDRESS", ""),
        "state_code": os.environ.get("AXON_SELLER_STATE_CODE", ""),
        "invoice_prefix": os.environ.get("AXON_INVOICE_PREFIX", "AXN"),
    }
