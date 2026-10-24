"""Contract tests: each adapter's health call against the real vendor. Skipped until keys exist."""

import asyncio

import pytest

from app.providers.speech.cartesia import CartesiaTTS
from app.providers.speech.gemini import GeminiLLM
from app.providers.speech.sarvam import SarvamLLM, SarvamSTT, SarvamTTS
from app.providers.speech.smallest import SmallestSTT, SmallestTTS


@pytest.mark.requires_keys("SARVAM_API_KEY")
@pytest.mark.parametrize("adapter", [SarvamSTT, SarvamTTS, SarvamLLM])
def test_sarvam_accepts_our_key(adapter: type[SarvamSTT | SarvamTTS | SarvamLLM]) -> None:
    asyncio.run(adapter().health())


@pytest.mark.requires_keys("SMALLEST_API_KEY")
@pytest.mark.parametrize("adapter", [SmallestSTT, SmallestTTS])
def test_smallest_accepts_our_key(adapter: type[SmallestSTT | SmallestTTS]) -> None:
    asyncio.run(adapter().health())


@pytest.mark.requires_keys("CARTESIA_API_KEY")
def test_cartesia_accepts_our_key() -> None:
    asyncio.run(CartesiaTTS().health())


@pytest.mark.requires_keys("GEMINI_API_KEY")
def test_gemini_accepts_our_key() -> None:
    asyncio.run(GeminiLLM().health())
