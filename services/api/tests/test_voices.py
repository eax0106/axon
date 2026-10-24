import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.models import Voice, VoiceTier
from app.voices import SEED

from .helpers import seed, signup


@pytest.fixture
def api(db_client: TestClient, migrated_url: str) -> TestClient:
    seed(migrated_url)
    return db_client


def test_seed_covers_every_tier_and_language_and_is_idempotent(
    api: TestClient, migrated_url: str
) -> None:
    from .conftest import sql

    seed(migrated_url)  # again: no duplicates
    assert sql(migrated_url, "SELECT count(*) FROM voices") == len(SEED)
    owner = signup(api)
    for tier in VoiceTier:
        voices = api.get(f"/voices?tier={tier}", headers=owner).json()
        assert voices and {v["tier"] for v in voices} == {tier.value}
    for language in ("te", "hi", "en"):
        assert api.get(f"/voices?language={language}&tier=value", headers=owner).json()


def test_picker_filters_by_language_and_tier(api: TestClient) -> None:
    owner = signup(api)
    telugu = api.get("/voices?language=te", headers=owner).json()
    assert telugu and all("te" in v["languages"] for v in telugu)
    assert {v["provider"] for v in telugu} == {"sarvam", "smallest"}  # Cartesia has none yet
    assert api.get("/voices?language=ta", headers=owner).status_code == 422
    assert api.get("/voices").status_code == 401


def test_each_vendor_voice_maps_to_its_tier() -> None:
    assert {(provider, tier) for provider, _, tier, *_ in SEED} == {
        ("sarvam", VoiceTier.VALUE),
        ("smallest", VoiceTier.STANDARD),
        ("cartesia", VoiceTier.PREMIUM),
    }


def test_catalog_rows_are_unique_per_vendor_voice(api: TestClient, migrated_url: str) -> None:
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    async def count() -> int:
        engine = create_async_engine(migrated_url)
        async with async_sessionmaker(engine)() as session:
            total = await session.scalar(select(func.count()).select_from(Voice))
        await engine.dispose()
        return total or 0

    assert asyncio.run(count()) == len(SEED)


def test_preview_speaks_a_sample_through_the_voices_own_vendor(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import base64
    import json

    import httpx

    from app.providers.speech import common

    wav = b"RIFF\x24\x00\x00\x00WAVEfmt " + bytes(20)
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"audios": [base64.b64encode(wav).decode()]})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        common.VendorHealth,
        "client",
        lambda self, timeout=60.0: httpx.AsyncClient(transport=transport),
    )
    owner = signup(api)
    voice = next(
        v
        for v in api.get("/voices?tier=value&language=te", headers=owner).json()
        if v["name"] == "Shubh"
    )
    path = f"/voices/{voice['id']}/preview"
    assert api.post(path + "?language=te", headers=owner).status_code == 503  # no Sarvam key yet
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")
    response = api.post(path + "?language=te&speed=1.5", headers=owner)
    assert response.status_code == 200 and response.content == wav
    assert response.headers["content-type"] == "audio/wav"
    body = json.loads(seen[0].content)
    assert body["speaker"] == "shubh" and body["language_code"] == "te-IN" and body["pace"] == 1.5
    assert body["text"].startswith("నమస్కారం")


def test_preview_rejects_unknown_voices_languages_and_speeds(api: TestClient) -> None:
    import uuid

    owner = signup(api)
    telugu_only = next(
        v
        for v in api.get("/voices?tier=standard", headers=owner).json()
        if v["languages"] == ["te"]
    )
    assert api.post(f"/voices/{uuid.uuid4()}/preview", headers=owner).status_code == 404
    assert (
        api.post(f"/voices/{telugu_only['id']}/preview?language=en", headers=owner).status_code
        == 422
    )
    assert (
        api.post(
            f"/voices/{telugu_only['id']}/preview?language=te&speed=5", headers=owner
        ).status_code
        == 422
    )
    assert (
        api.post(f"/voices/{telugu_only['id']}/preview?language=ta", headers=owner).status_code
        == 422
    )
    assert api.post(f"/voices/{telugu_only['id']}/preview").status_code == 401
