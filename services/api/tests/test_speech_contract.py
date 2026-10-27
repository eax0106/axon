"""Contract tests: each adapter's health call against the real vendor. Skipped until keys exist."""

import asyncio

import pytest

from app.providers.speech.cartesia import CartesiaTTS
from app.providers.speech.gemini import EMBEDDING_DIMENSIONS, GeminiEmbedding, GeminiLLM
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


@pytest.mark.requires_keys("GEMINI_API_KEY")
def test_gemini_embeddings_are_unit_vectors_and_rank_by_meaning() -> None:
    texts = ["The premium plan costs 4999 rupees a month.", "We deliver only within Hyderabad."]
    [plan, delivery], [question] = (
        asyncio.run(GeminiEmbedding().embed(texts)),
        asyncio.run(GeminiEmbedding().embed(["How much is the premium plan?"], query=True)),
    )
    assert len(plan) == EMBEDDING_DIMENSIONS

    def dot(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b, strict=True))

    assert dot(plan, plan) == pytest.approx(1.0) and dot(question, plan) > dot(question, delivery)
