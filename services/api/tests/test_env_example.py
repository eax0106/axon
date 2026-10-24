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
