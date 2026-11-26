"""Time-based one-time passwords (RFC 6238, on HOTP from RFC 4226), as authenticator apps make
them: a 20-byte seed shown as base32, SHA-1, 6 digits, a new code every 30 seconds."""

import base64
import hashlib
import hmac
import secrets
import struct
from urllib.parse import quote, urlencode

STEP_S = 30
DIGITS = 6
DRIFT_STEPS = 1  # also accept the code just before and just after: phone clocks drift


def new_seed() -> str:
    """A fresh seed in base32 without padding, as authenticator apps take it."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _seed_bytes(seed: str) -> bytes:
    clean = seed.replace(" ", "").upper()
    return base64.b32decode(clean + "=" * (-len(clean) % 8))


def hotp(key: bytes, counter: int, digits: int = DIGITS, algorithm: str = "sha1") -> str:
    mac = hmac.new(key, struct.pack(">Q", counter), getattr(hashlib, algorithm)).digest()
    offset = mac[-1] & 0x0F
    number = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10**digits).zfill(digits)


def step_of(at: float) -> int:
    return int(at // STEP_S)


def code_at(seed: str, at: float) -> str:
    return hotp(_seed_bytes(seed), step_of(at))


def match(seed: str, code: str, at: float, last_step: int | None) -> int | None:
    """The step `code` belongs to, if it is right within the drift window and newer than the last
    step used (a code works once); otherwise None. Compared in constant time."""
    code = code.strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    key, now = _seed_bytes(seed), step_of(at)
    found = None
    for step in range(now - DRIFT_STEPS, now + DRIFT_STEPS + 1):
        if hmac.compare_digest(hotp(key, step), code) and (last_step is None or step > last_step):
            found = step
    return found


def otpauth_uri(seed: str, account: str, issuer: str = "Axon") -> str:
    """The link an authenticator app reads (its QR code holds exactly this text)."""
    label = quote(f"{issuer}:{account}")
    query = urlencode({"secret": seed, "issuer": issuer, "algorithm": "SHA1", "digits": DIGITS,
                       "period": STEP_S})  # fmt: skip
    return f"otpauth://totp/{label}?{query}"
