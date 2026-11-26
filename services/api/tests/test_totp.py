"""The second factor's code maker, checked against the RFC 6238 appendix B test vectors."""

import base64
from urllib.parse import parse_qs, urlsplit

import pytest

from app import totp

# RFC 6238 appendix B: the seeds are the ASCII digits repeated to the hash's block length.
SEEDS = {
    "sha1": b"12345678901234567890",
    "sha256": b"12345678901234567890123456789012",
    "sha512": b"1234567890123456789012345678901234567890123456789012345678901234",
}
VECTORS = [
    (59, "94287082", "46119246", "90693936"),
    (1111111109, "07081804", "68084774", "25091201"),
    (1111111111, "14050471", "67062674", "99943326"),
    (1234567890, "89005924", "91819424", "93441116"),
    (2000000000, "69279037", "90698825", "38618901"),
    (20000000000, "65353130", "77737706", "47863826"),
]


@pytest.mark.parametrize(("at", "sha1", "sha256", "sha512"), VECTORS)
def test_codes_match_the_rfc_6238_test_vectors(
    at: int, sha1: str, sha256: str, sha512: str
) -> None:
    for algorithm, expected in (("sha1", sha1), ("sha256", sha256), ("sha512", sha512)):
        assert totp.hotp(SEEDS[algorithm], totp.step_of(at), 8, algorithm) == expected


def test_a_base32_seed_gives_the_six_digit_code_an_authenticator_app_shows() -> None:
    seed = base64.b32encode(SEEDS["sha1"]).decode().rstrip("=")
    assert totp.code_at(seed, 59) == "287082"  # the last six digits of the 8-digit vector
    assert totp.code_at(seed.lower(), 59) == "287082"  # apps and people type it either way


def test_a_code_is_accepted_one_step_either_side_and_only_once() -> None:
    seed, now = totp.new_seed(), 1_700_000_000.0
    step = totp.step_of(now)
    assert totp.match(seed, totp.code_at(seed, now), now, None) == step
    assert totp.match(seed, totp.code_at(seed, now - 30), now, None) == step - 1  # slow clock
    assert totp.match(seed, totp.code_at(seed, now + 30), now, None) == step + 1  # fast clock
    assert totp.match(seed, totp.code_at(seed, now - 60), now, None) is None  # too old
    assert totp.match(seed, totp.code_at(seed, now), now, step) is None  # already used
    assert totp.match(seed, totp.code_at(seed, now - 30), now, step) is None  # older than used
    assert (
        totp.match(
            seed, " " + totp.code_at(seed, now)[:3] + " " + totp.code_at(seed, now)[3:], now, None
        )
        == step
    )


def test_anything_but_six_digits_is_refused() -> None:
    seed = totp.new_seed()
    for code in ("", "12345", "1234567", "abcdef", "12345a"):
        assert totp.match(seed, code, 0, None) is None


def test_a_new_seed_is_160_random_bits_in_base32() -> None:
    seeds = {totp.new_seed() for _ in range(50)}
    assert len(seeds) == 50
    assert all(len(base64.b32decode(s)) == 20 for s in seeds)


def test_the_otpauth_link_carries_what_an_authenticator_app_needs() -> None:
    uri = totp.otpauth_uri("JBSWY3DPEHPK3PXP", "staff@alterx.in")
    parts = urlsplit(uri)
    assert (parts.scheme, parts.netloc, parts.path) == (
        "otpauth",
        "totp",
        "/Axon%3Astaff%40alterx.in",
    )
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert query == {"secret": "JBSWY3DPEHPK3PXP", "issuer": "Axon", "algorithm": "SHA1",
                     "digits": "6", "period": "30"}  # fmt: skip
