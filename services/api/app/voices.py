"""The voice catalog: seeded rows, the picker, and the voice an employee gets by default.

`language_scores` holds a key for every language the vendor documents for that voice. The values
are a conservative 0.7 placeholder ("good"): real per-language scores come from the native-speaker
checks in Track 3, so do not read them as measurements.
"""

import asyncio
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth import CurrentUser
from app.db import Session
from app.employees.limits import AiBudget
from app.models import Voice, VoiceTier
from app.providers.base import ProviderKind, TextToSpeechProvider
from app.providers.registry import resolve
from app.settings import get_settings

# ponytail: placeholder scores until native-speaker QA (B14) measures each voice. They only say
# "documented to speak this language"; nothing may rank or pick voices by the value.
ALL = {"te": 0.7, "hi": 0.7, "en": 0.7}
# (provider, provider_voice_id, tier, public_name, native_language, language_scores)
SEED: tuple[tuple[str, str, VoiceTier, str, str, dict[str, float]], ...] = (
    *(
        ("sarvam", speaker, VoiceTier.VALUE, speaker.capitalize(), "hi", ALL)
        for speaker in ("shubh", "ritu", "priya", "aditya", "kavya", "amit")
    ),
    ("smallest", "srihari", VoiceTier.STANDARD, "Srihari", "te", {"te": 0.7}),
    ("smallest", "padmaja", VoiceTier.STANDARD, "Padmaja", "te", {"te": 0.7}),
    ("smallest", "devansh", VoiceTier.STANDARD, "Devansh", "hi", {"hi": 0.7, "en": 0.7}),
    ("smallest", "sunidhi", VoiceTier.STANDARD, "Sunidhi", "hi", {"hi": 0.7, "en": 0.7}),
    ("smallest", "avery", VoiceTier.STANDARD, "Avery", "en", {"en": 0.7}),
    ("smallest", "liam", VoiceTier.STANDARD, "Liam", "en", {"en": 0.7}),
    # Cartesia documents English voices only; Hindi and Telugu voices are added with the key.
    (
        "cartesia",
        "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4",
        VoiceTier.PREMIUM,
        "Skylar",
        "en",
        {"en": 0.7},
    ),
    (
        "cartesia",
        "47c38ca4-5f35-497b-b1a3-415245fb35e1",
        VoiceTier.PREMIUM,
        "Daniel",
        "en",
        {"en": 0.7},
    ),
)


async def seed_voices(session: AsyncSession) -> None:
    """Insert the catalog; existing rows are left alone, so it is safe to run on every deploy."""
    rows = [
        {
            "provider": provider,
            "provider_voice_id": voice_id,
            "tier": tier,
            "public_name": name,
            "native_language": native,
            "language_scores": scores,
        }
        for provider, voice_id, tier, name, native, scores in SEED
    ]
    await session.execute(insert(Voice).values(rows).on_conflict_do_nothing())
    await session.commit()


async def default_voice(session: AsyncSession, language: str, tier: VoiceTier) -> Voice | None:
    voices = await session.scalars(
        select(Voice).where(Voice.tier == tier).order_by(Voice.provider, Voice.public_name)
    )
    return next((v for v in voices if language in v.language_scores), None)


def supports(voice: Voice, languages: list[str]) -> bool:
    return all(language in voice.language_scores for language in languages)


class VoiceOut(BaseModel):
    id: uuid.UUID
    provider: str
    tier: VoiceTier
    name: str
    native_language: str
    accent: str | None
    tone_tags: list[str]
    languages: list[str]


def voice_out(voice: Voice) -> VoiceOut:
    return VoiceOut(
        id=voice.id,
        provider=voice.provider,
        tier=voice.tier,
        name=voice.public_name,
        native_language=voice.native_language,
        accent=voice.accent,
        tone_tags=voice.tone_tags,
        languages=sorted(voice.language_scores),
    )


router = APIRouter()

SAMPLES = {
    "te": "నమస్కారం, నేను మీ సహాయకుడిని. ఈరోజు నేను మీకు ఎలా సహాయం చేయగలను?",
    "hi": "नमस्ते, मैं आपका सहायक हूँ। आज मैं आपकी कैसे मदद कर सकता हूँ?",
    "en": "Hello, I am your assistant. How can I help you today?",
}


@router.get("/voices")
async def list_voices(
    _: CurrentUser,
    session: Session,
    language: Annotated[str | None, Query(pattern="^(te|hi|en)$")] = None,
    tier: VoiceTier | None = None,
) -> list[VoiceOut]:
    query = select(Voice).order_by(Voice.tier, Voice.provider, Voice.public_name)
    if tier:
        query = query.where(Voice.tier == tier)
    voices = await session.scalars(query)
    return [voice_out(v) for v in voices if language is None or language in v.language_scores]


@router.post("/voices/{voice_id}/preview", dependencies=[AiBudget])
async def preview(
    voice_id: uuid.UUID,
    _: CurrentUser,
    session: Session,
    language: Annotated[str, Query(pattern="^(te|hi|en)$")] = "en",
    speed: Annotated[float, Query(ge=0.5, le=2.0)] = 1.0,
) -> Response:
    """A short spoken sample of the voice as a WAV, made by the voice's own vendor."""
    voice = await session.get(Voice, voice_id)
    if voice is None:
        raise HTTPException(404, "voice not found")
    if language not in voice.language_scores:
        raise HTTPException(422, f"{voice.public_name} does not speak {language!r}")
    tts = resolve(ProviderKind.TTS, voice.provider)
    assert isinstance(tts, TextToSpeechProvider)
    wav = await tts.synthesize(SAMPLES[language], voice.provider_voice_id, language, speed)
    return Response(wav, media_type="audio/wav")


async def _seed() -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            await seed_voices(session)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_seed())
    print("voices seeded")
