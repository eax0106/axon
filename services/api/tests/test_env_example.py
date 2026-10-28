import re
import subprocess
from pathlib import Path

from app.providers.base import ProviderKind
from app.providers.registry import VENDOR_KEYS

ROOT = Path(__file__).parents[3]
NON_PROVIDER_VARS = {
    "DATABASE_URL",
    "REDIS_URL",
    "AXON_JWT_SECRET",
    "AXON_TEST_DATABASE_URL",
    "AXON_TEST_REDIS_URL",
    "AXON_ENGINE_PUBLIC_URL",
    "AXON_API_PUBLIC_URL",
    "AXON_GEMINI_MODEL",
    "AXON_GEMINI_EMBEDDING_MODEL",
    "AXON_AMBIENCE_DIR",
    "AXON_MAX_CONCURRENT_CALLS",
    "CARTESIA_VOICE_EN",
    "CARTESIA_VOICE_HI",
    "CARTESIA_VOICE_TE",
    "AXON_RATE_VALUE_PER_MIN",
    "AXON_RATE_STANDARD_PER_MIN",
    "AXON_RATE_PREMIUM_PER_MIN",
    "AXON_AI_USE_FEE",
    "AXON_FREE_CREDITS",
    "AXON_NUMBER_MONTHLY_FEE",
    "AXON_NUMBER_SETUP_FEE",
    "AXON_EXTRA_CHANNEL_FEE",
    "AXON_TOPUP_MIN",
    "AXON_TOPUP_MAX",
    "AXON_LOW_BALANCE",
    "AXON_NUMBER_GRACE_DAYS",
    "AXON_GST_RATE",
    "AXON_GST_SAC",
    "AXON_SELLER_NAME",
    "AXON_SELLER_GSTIN",
    "AXON_SELLER_ADDRESS",
    "AXON_SELLER_STATE_CODE",
    "AXON_INVOICE_PREFIX",
}


def test_env_example_lists_exactly_the_registry_keys_and_selectors() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    listed = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]*)=", text, flags=re.MULTILINE))
    keys = {key for vendors in VENDOR_KEYS.values() for keys in vendors.values() for key in keys}
    selectors = {f"AXON_{kind.upper()}_PROVIDER" for kind in ProviderKind if VENDOR_KEYS[kind]}
    assert listed == keys | selectors | NON_PROVIDER_VARS


def test_env_example_leaves_every_provider_key_empty() -> None:
    keys = {key for vendors in VENDOR_KEYS.values() for keys in vendors.values() for key in keys}
    values = dict(
        re.findall(
            r"^([A-Z][A-Z0-9_]*)=(.*)$",
            (ROOT / ".env.example").read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        )
    )
    assert {key: values[key] for key in keys} == dict.fromkeys(keys, "")


def test_no_env_file_is_tracked() -> None:
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert ".env.example" in tracked
    assert [f for f in tracked if Path(f).name.startswith(".env") and f != ".env.example"] == []
