"""Contract tests: each adapter's health call against the real vendor. Skipped until keys exist."""

import asyncio

import pytest

from app.providers.speech.cartesia import CartesiaTTS
from app.providers.speech.elevenlabs import ElevenLabsSTT
from app.providers.speech.gemini import EMBEDDING_DIMENSIONS, GeminiEmbedding, GeminiLLM
from app.providers.speech.sarvam import SarvamLLM, SarvamSTT, SarvamTTS
from app.providers.speech.smallest import SmallestSTT, SmallestTTS
from app.providers.speech.soniox import SonioxSTT


@pytest.mark.requires_keys("SARVAM_API_KEY")
@pytest.mark.parametrize("adapter", [SarvamSTT, SarvamTTS, SarvamLLM])
def test_sarvam_accepts_our_key(adapter: type[SarvamSTT | SarvamTTS | SarvamLLM]) -> None:
    asyncio.run(adapter().health())


@pytest.mark.requires_keys("SMALLEST_API_KEY")
@pytest.mark.parametrize("adapter", [SmallestSTT, SmallestTTS])
def test_smallest_accepts_our_key(adapter: type[SmallestSTT | SmallestTTS]) -> None:
    asyncio.run(adapter().health())


@pytest.mark.requires_keys("SONIOX_API_KEY")
def test_soniox_accepts_our_key_and_offers_our_models() -> None:
    import httpx

    from app.providers.speech import soniox

    asyncio.run(SonioxSTT().health())
    reply = httpx.get(soniox.BASE + "/models", headers=SonioxSTT().headers(), timeout=10)
    models = {m["id"]: m for m in reply.json()["models"]}
    for model in (soniox.RT_MODEL, soniox.ASYNC_MODEL):
        codes = {lang["code"] for lang in models[model]["languages"]}
        assert {"te", "hi", "en"} <= codes, (model, codes)


@pytest.mark.requires_keys("ELEVENLABS_API_KEY")
def test_elevenlabs_accepts_our_key() -> None:
    asyncio.run(ElevenLabsSTT().health())


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
