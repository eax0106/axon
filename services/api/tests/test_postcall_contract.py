"""Real-use contract tests for what B6 asks of the vendors: the LLM extracting from a real
transcript, and the object store taking an upload and serving it back through a presigned link.
Skipped until the keys exist (`requires_keys`)."""

import asyncio
import uuid
from datetime import UTC, datetime

import httpx
import pytest

from app.calls import analysis
from app.employees.script import CaptureField
from app.providers.speech.gemini import GeminiLLM
from app.providers.speech.sarvam import SarvamLLM
from app.providers.storage.r2 import R2Storage

NOW = datetime(2026, 11, 2, 8, 0, tzinfo=UTC)
CAPTURE = [
    CaptureField(name="city", description="City"),
    CaptureField(name="budget", description="Budget"),
]
TURNS = [
    {"role": "assistant", "text": "Hello, this is Asha from SunBright Solar. Is this a good time?"},
    {
        "role": "user",
        "text": "Yes. I am in Hyderabad. Please call me tomorrow at 6 in the evening.",
    },
]


def check(result: analysis.Analysis) -> None:
    assert result.captured == {"city": "Hyderabad", "budget": None}  # the budget was never said
    assert result.summary and result.outcome in analysis.OUTCOMES
    assert result.callback_at is not None and result.callback_at > NOW


@pytest.mark.requires_keys("GEMINI_API_KEY")
def test_gemini_extracts_only_what_was_said() -> None:
    check(asyncio.run(analysis.analyse(GeminiLLM(), TURNS, CAPTURE, NOW)))


@pytest.mark.requires_keys("SARVAM_API_KEY")
def test_sarvam_extracts_only_what_was_said() -> None:
    check(asyncio.run(analysis.analyse(SarvamLLM(), TURNS, CAPTURE, NOW)))


@pytest.mark.requires_keys(
    "S3_ENDPOINT_URL", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_BUCKET"
)
def test_the_bucket_accepts_our_signature() -> None:
    asyncio.run(R2Storage().health())


@pytest.mark.requires_keys(
    "S3_ENDPOINT_URL", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_BUCKET"
)
def test_an_uploaded_recording_can_be_read_back_through_a_presigned_link() -> None:
    storage = R2Storage()
    key = f"contract-tests/{uuid.uuid4()}.wav"
    body = b"RIFF" + bytes(64)
    asyncio.run(storage.put(key, body, "audio/wav"))
    assert httpx.get(storage.presigned_url(key, 60), timeout=30).content == body
