"""Real-use contract tests for what B4 asks of the vendors: LLM drafting, voice previews,
transcription and placing a call. Skipped until the vendor's key exists (`requires_keys`).

The Hindi and Telugu Cartesia voices are not in the catalog yet, so Cartesia previews run for
English only. The call test places a real call: set AXON_TEST_FROM to a number on the account and
AXON_TEST_PHONE to the phone that should ring.
"""

import asyncio
import json
import os
import wave
from pathlib import Path

import pytest

from app.employees.ai import parse_json
from app.providers.speech.cartesia import CartesiaTTS
from app.providers.speech.gemini import GeminiLLM
from app.providers.speech.sarvam import SarvamLLM, SarvamSTT, SarvamTTS
from app.providers.speech.smallest import SmallestSTT, SmallestTTS
from app.providers.telephony.vobiz import VobizTelephony
from app.voices import SAMPLES, SEED

FIXTURES = Path(__file__).parents[2] / "engine" / "engine_tests" / "fixtures"
LANGUAGES = ["te", "hi", "en"]
PROMPT = 'Reply with one JSON object only: {"ok": true}'


def voice_for(provider: str, language: str) -> str:
    return next(vid for p, vid, _, _, _, scores in SEED if p == provider and language in scores)


def assert_wav(audio: bytes) -> None:
    assert audio[:4] == b"RIFF" and len(audio) > 1000


@pytest.mark.requires_keys("GEMINI_API_KEY")
def test_gemini_returns_json_in_json_mode() -> None:
    reply = asyncio.run(
        GeminiLLM().complete(PROMPT, [{"role": "user", "content": "go"}], json_output=True)
    )
    assert parse_json(reply) == {"ok": True}


@pytest.mark.requires_keys("SARVAM_API_KEY")
def test_sarvam_llm_returns_json_in_json_mode() -> None:
    reply = asyncio.run(
        SarvamLLM().complete(PROMPT, [{"role": "user", "content": "go"}], json_output=True)
    )
    assert parse_json(reply) == {"ok": True}


@pytest.mark.requires_keys("SARVAM_API_KEY")
@pytest.mark.parametrize("language", LANGUAGES)
def test_sarvam_voice_preview(language: str) -> None:
    audio = asyncio.run(
        SarvamTTS().synthesize(SAMPLES[language], voice_for("sarvam", language), language, 1.0)
    )
    assert_wav(audio)


@pytest.mark.requires_keys("SMALLEST_API_KEY")
@pytest.mark.parametrize("language", LANGUAGES)
def test_smallest_voice_preview(language: str) -> None:
    audio = asyncio.run(
        SmallestTTS().synthesize(SAMPLES[language], voice_for("smallest", language), language, 1.0)
    )
    assert_wav(audio)


@pytest.mark.requires_keys("CARTESIA_API_KEY")
def test_cartesia_voice_preview_in_english() -> None:
    audio = asyncio.run(
        CartesiaTTS().synthesize(SAMPLES["en"], voice_for("cartesia", "en"), "en", 1.0)
    )
    assert_wav(audio)


@pytest.mark.requires_keys("SARVAM_API_KEY")
@pytest.mark.parametrize("language", LANGUAGES)
def test_sarvam_transcribes_the_fixture_clip(language: str) -> None:
    assert asyncio.run(
        SarvamSTT().transcribe((FIXTURES / f"hello_{language}.wav").read_bytes(), language)
    ).strip()


@pytest.mark.requires_keys("SMALLEST_API_KEY")
@pytest.mark.parametrize("language", LANGUAGES)
def test_smallest_transcribes_the_fixture_clip(language: str) -> None:
    assert asyncio.run(
        SmallestSTT().transcribe((FIXTURES / f"hello_{language}.wav").read_bytes(), language)
    ).strip()


@pytest.mark.requires_keys("VOBIZ_AUTH_ID", "VOBIZ_AUTH_TOKEN", "AXON_TEST_FROM", "AXON_TEST_PHONE")
def test_vobiz_places_a_call() -> None:
    call_id = asyncio.run(
        VobizTelephony().originate(
            os.environ["AXON_TEST_FROM"],
            os.environ["AXON_TEST_PHONE"],
            os.environ.get("AXON_ENGINE_PUBLIC_URL", "https://example.invalid") + "/vobiz/answer",
        )
    )
    assert call_id


def test_the_fixture_clips_are_what_the_contract_tests_expect() -> None:
    for language in LANGUAGES:
        with wave.open(str(FIXTURES / f"hello_{language}.wav")) as clip:
            assert (clip.getframerate(), clip.getnchannels()) == (16000, 1)
    assert json.loads(PROMPT.split(": ", 1)[1]) == {"ok": True}
