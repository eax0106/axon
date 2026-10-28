"""Voice tiers on the way down: which text-to-speech vendors a call may fall back to, in what
order, and what a call that fell back is billed at."""

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.conftest import sql
from tests.helpers import add_call, seed, signup

from app.models import VoiceTier
from app.providers.base import ProviderKind, ProviderNotConfiguredError
from app.providers.failover import billed_tier, chain
from app.providers.registry import VENDOR_KEYS
from engine.legs import ServiceLeg, voice_legs

from .test_call import events
from .vendors import call, switches, vendors, wire

__all__ = ["events", "vendors", "wire"]
TTS = ProviderKind.TTS


@pytest.fixture
def keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for vendors_ in VENDOR_KEYS.values():
        for names in vendors_.values():
            for key in names:
                monkeypatch.setenv(key, "test-key")
    for kind in ("STT", "LLM", "TTS"):
        monkeypatch.delenv(f"AXON_{kind}_PROVIDER", raising=False)
    monkeypatch.delenv("CARTESIA_VOICE_TE", raising=False)


def order(leg: ServiceLeg) -> list[str]:
    return [leg.vendors[s] for s in leg.services]


def test_premium_falls_back_to_value_then_standard_and_nothing_falls_back_to_premium() -> None:
    assert chain(TTS, VoiceTier.PREMIUM) == ["cartesia", "sarvam", "smallest"]
    assert chain(TTS, VoiceTier.VALUE) == ["sarvam", "smallest"]
    assert chain(TTS, VoiceTier.STANDARD) == ["smallest", "sarvam"]


def test_a_call_is_billed_at_the_cheapest_tier_it_used() -> None:
    assert billed_tier([VoiceTier.PREMIUM, VoiceTier.VALUE]) is VoiceTier.VALUE
    assert billed_tier([VoiceTier.PREMIUM, VoiceTier.STANDARD]) is VoiceTier.STANDARD
    assert billed_tier([VoiceTier.STANDARD, VoiceTier.VALUE]) is VoiceTier.VALUE
    assert billed_tier([VoiceTier.VALUE, VoiceTier.STANDARD]) is VoiceTier.VALUE
    assert billed_tier([VoiceTier.PREMIUM, None]) is VoiceTier.PREMIUM
    assert billed_tier([]) is None


def test_the_cheapest_tier_follows_the_configured_rates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AXON_RATE_STANDARD_PER_MIN", "3")  # Standard now costs less than Value
    assert billed_tier([VoiceTier.VALUE, VoiceTier.STANDARD]) is VoiceTier.STANDARD
    assert billed_tier([VoiceTier.PREMIUM, VoiceTier.VALUE, VoiceTier.STANDARD]) is (
        VoiceTier.STANDARD
    )
    monkeypatch.setenv("AXON_RATE_STANDARD_PER_MIN", "3.5")  # a tie keeps the list order
    assert billed_tier([VoiceTier.STANDARD, VoiceTier.VALUE]) is VoiceTier.VALUE


def test_a_vendor_that_cannot_be_built_is_skipped(
    keys: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Cartesia has no Telugu voice until one is configured: a Telugu Premium call starts on Value.
    assert order(voice_legs("te", VoiceTier.PREMIUM)[2]) == ["sarvam", "smallest"]
    monkeypatch.setenv("CARTESIA_VOICE_TE", "voice-te")
    assert order(voice_legs("te", VoiceTier.PREMIUM)[2]) == ["cartesia", "sarvam", "smallest"]
    monkeypatch.delenv("SARVAM_API_KEY")
    stt, llm, tts = voice_legs("te", VoiceTier.PREMIUM)
    assert order(tts) == ["cartesia", "smallest"]
    assert order(stt) == ["smallest"] and order(llm) == ["gemini"]


def test_unhealthy_vendors_are_tried_last(keys: None) -> None:
    down = frozenset({("tts", "cartesia"), ("stt", "sarvam")})
    stt, llm, tts = voice_legs("en", VoiceTier.PREMIUM, down=down)
    assert order(tts) == ["sarvam", "smallest", "cartesia"]
    assert order(stt) == ["smallest", "sarvam"]
    assert order(llm) == ["gemini", "sarvam"]


def test_with_no_vendor_left_for_a_leg_the_call_is_refused_with_what_is_missing(
    keys: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Every voice gone, speech-to-text and the LLM still there (they share keys, so rename them).
    for vendor in VENDOR_KEYS[TTS]:
        monkeypatch.setitem(VENDOR_KEYS[TTS], vendor, (f"{vendor.upper()}_VOICE_OFF",))
    with pytest.raises(ProviderNotConfiguredError) as raised:
        voice_legs("en", VoiceTier.VALUE)
    assert raised.value.kind is TTS
    assert raised.value.missing_keys == ["SARVAM_VOICE_OFF"]  # the leg's first vendor


def test_a_premium_call_that_fell_back_to_value_is_billed_at_value(
    db_client: TestClient,
    migrated_url: str,
    wire: Callable[..., dict[str, str]],
    events: list[dict[str, Any]],
) -> None:
    seed(migrated_url)
    signup(db_client)
    account = sql(migrated_url, "SELECT id FROM accounts")
    call_id = add_call(migrated_url, account, status="ringing")
    wire(voice_tier="premium")
    call(events, f"?call={call_id}")

    assert switches(events)["tts"] == ("badtts", "goodtts")
    assert {"type": "tier_fallback", "tier": "value"} in events
    assert sql(migrated_url, "SELECT voice_tier FROM calls") == "value"
    outcomes = sql(
        migrated_url,
        "SELECT string_agg(kind || ':' || vendor || ':' || ok, ',' ORDER BY kind, vendor)"
        " FROM provider_outcomes",
    )
    assert outcomes.split(",") == [
        "llm:badllm:false",
        "llm:goodllm:true",
        "stt:badstt:false",
        "stt:goodstt:true",
        "tts:badtts:false",
        "tts:goodtts:true",
    ]
