"""Secrets kept in the database (webhook signing secrets, lead-intake secrets, Google and Meta
tokens, action keys, staff second-factor seeds) are stored encrypted with Fernet (AES-128-CBC with
an HMAC-SHA256 tag) under `AXON_SECRETS_KEY`, which never enters the database.

The setting is a comma-separated list of keys, newest first. New values are written with the
first key; any listed key can read. To rotate: put a new key in front, restart, run
`python -m app.secretbox rotate` (re-encrypts every stored secret under the new key), then drop
the old key. `python -m app.secretbox new-key` prints a fresh key.
"""

import os
import sys
from functools import cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

KEY_ENV = "AXON_SECRETS_KEY"
HOW_TO_SET = (
    f"{KEY_ENV} must be set to one or more Fernet keys, newest first, comma-separated. Make one"
    " with: uv run python -m app.secretbox new-key"
)


class SecretsNotConfiguredError(RuntimeError):
    def __init__(self, detail: str = HOW_TO_SET) -> None:
        super().__init__(detail)


@cache
def _box(raw: str) -> MultiFernet:
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise SecretsNotConfiguredError
    try:
        return MultiFernet([Fernet(k) for k in keys])
    except ValueError as exc:
        raise SecretsNotConfiguredError(
            f"{KEY_ENV} holds a key that is not a Fernet key. {HOW_TO_SET}"
        ) from exc


def box() -> MultiFernet:
    """The keys from the environment, or SecretsNotConfiguredError saying what to set."""
    return _box(os.environ.get(KEY_ENV, ""))


def check() -> None:
    """Called at startup: refuse to run without a usable key, not fail at the first secret."""
    box()


def seal(value: str) -> str:
    return box().encrypt(value.encode()).decode()


def unseal(token: str) -> str:
    try:
        return box().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise SecretsNotConfiguredError(
            f"a stored secret cannot be read with any key in {KEY_ENV}: was a key dropped too soon?"
        ) from exc


def reseal(token: str) -> str:
    """The same secret under the newest key."""
    try:
        return box().rotate(token.encode()).decode()
    except InvalidToken as exc:
        raise SecretsNotConfiguredError(
            f"a stored secret cannot be read with any key in {KEY_ENV}"
        ) from exc


class EncryptedText(TypeDecorator[str]):
    """A text column whose value is stored encrypted and read back in the clear."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        return None if value is None else seal(value)

    def process_result_value(self, value: str | None, dialect: Dialect) -> str | None:
        return None if value is None else unseal(value)


# Where secrets sit inside an employee's script bundle (`employees.draft`, `employee_versions
# .bundle`): an HTTP action's key and the result webhook's signing secret.
def map_bundle_secrets(bundle: dict[str, Any], change: Any) -> dict[str, Any]:
    """A copy of `bundle` with `change` applied to every non-empty secret in it."""
    out = dict(bundle)
    actions = out.get("actions")
    if isinstance(actions, list):
        out["actions"] = [_map_action(a, change) for a in actions]
    hook = out.get("result_webhook")
    if isinstance(hook, dict) and hook.get("secret"):
        out["result_webhook"] = {**hook, "secret": change(hook["secret"])}
    return out


def _map_action(action: Any, change: Any) -> Any:
    auth = action.get("auth") if isinstance(action, dict) else None
    if isinstance(auth, dict) and auth.get("secret"):
        return {**action, "auth": {**auth, "secret": change(auth["secret"])}}
    return action


class SealedBundle(TypeDecorator[dict[str, Any]]):
    """A script bundle (JSONB) whose secrets are stored encrypted; the rest stays plain JSON."""

    impl = JSONB
    cache_ok = True

    def process_bind_param(
        self, value: dict[str, Any] | None, dialect: Dialect
    ) -> dict[str, Any] | None:
        return None if value is None else map_bundle_secrets(value, seal)

    def process_result_value(
        self, value: dict[str, Any] | None, dialect: Dialect
    ) -> dict[str, Any] | None:
        return None if value is None else map_bundle_secrets(value, unseal)


def main(argv: list[str]) -> int:
    if argv == ["new-key"]:
        print(Fernet.generate_key().decode())
        return 0
    if argv == ["rotate"]:
        import asyncio

        from app.secretrotate import rotate_all

        counts = asyncio.run(rotate_all())
        print(", ".join(f"{name}: {n}" for name, n in counts.items()) or "nothing stored")
        return 0
    print("usage: python -m app.secretbox new-key | rotate", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
