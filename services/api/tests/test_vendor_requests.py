"""Request building and response parsing for the vendor calls the API makes itself (completion,
transcription, voice preview, call origination), against recorded real-shaped vendor payloads."""

import asyncio
import base64
import json
from typing import Any

import httpx
import pytest

from app.providers.speech.cartesia import CartesiaTTS
from app.providers.speech.gemini import GeminiLLM
from app.providers.speech.sarvam import SarvamLLM, SarvamSTT, SarvamTTS
from app.providers.speech.smallest import SmallestSTT, SmallestTTS
from app.providers.telephony.vobiz import VobizTelephony

WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + bytes(20)


def run(adapter_cls: Any, reply: httpx.Response, call: str, *args: Any, **kwargs: Any) -> Any:
    """Call `adapter.<call>` against a transport that records the request and returns `reply`."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return reply

    adapter = adapter_cls(transport=httpx.MockTransport(handler))
    result = asyncio.run(getattr(adapter, call)(*args, **kwargs))
    return result, seen[0]


@pytest.fixture(autouse=True)
def keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "SARVAM_API_KEY",
        "SMALLEST_API_KEY",
        "CARTESIA_API_KEY",
        "GEMINI_API_KEY",
        "VOBIZ_AUTH_TOKEN",
    ):
        monkeypatch.setenv(key, "test-key")
    monkeypatch.setenv("VOBIZ_AUTH_ID", "MA_TEST")
    monkeypatch.delenv("AXON_GEMINI_MODEL", raising=False)


def test_gemini_complete_builds_a_generate_content_request_and_reads_the_reply() -> None:
    reply = httpx.Response(
        200,
        json={
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": '{"ok": true}'}]},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 4},
        },
    )
    text, request = run(
        GeminiLLM,
        reply,
        "complete",
        "be brief",
        [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
        json_output=True,
    )
    assert text == '{"ok": true}'
    assert request.url.path == "/v1beta/models/gemini-2.5-flash:generateContent"
    assert request.headers["x-goog-api-key"] == "test-key"
    body = json.loads(request.content)
    assert body["systemInstruction"] == {"parts": [{"text": "be brief"}]}
    assert [c["role"] for c in body["contents"]] == ["user", "model"]
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}


def test_gemini_model_follows_the_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AXON_GEMINI_MODEL", "gemini-3.6-flash")
    reply = httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "x"}]}}]})
    _, request = run(GeminiLLM, reply, "complete", "s", [{"role": "user", "content": "q"}])
    assert request.url.path.endswith("/models/gemini-3.6-flash:generateContent")
    assert "responseMimeType" not in json.loads(request.content)["generationConfig"]


def test_sarvam_complete_sends_both_auth_headers_and_asks_for_json_mode() -> None:
    reply = httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": '{"a": 1}',
                        "reasoning_content": "...",
                    }
                }
            ]
        },
    )
    text, request = run(
        SarvamLLM, reply, "complete", "sys", [{"role": "user", "content": "q"}], json_output=True
    )
    assert text == '{"a": 1}'
    assert str(request.url) == "https://api.sarvam.ai/v1/chat/completions"
    assert request.headers["api-subscription-key"] == "test-key"
    assert request.headers["authorization"] == "Bearer test-key"
    body = json.loads(request.content)
    assert body["model"] == "sarvam-105b" and body["max_tokens"] >= 1500
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    assert body["response_format"] == {"type": "json_object"}


def test_sarvam_tts_requests_wav_and_decodes_the_base64_audio() -> None:
    reply = httpx.Response(
        200, json={"request_id": "r1", "audios": [base64.b64encode(WAV).decode()]}
    )
    audio, request = run(SarvamTTS, reply, "synthesize", "namaste", "shubh", "te", 1.2)
    assert audio == WAV
    assert str(request.url) == "https://api.sarvam.ai/text-to-speech"
    assert request.headers["api-subscription-key"] == "test-key"
    body = json.loads(request.content)
    assert body == {
        "text": "namaste",
        "language_code": "te-IN",
        "model": "bulbul:v3",
        "speaker": "shubh",
        "pace": 1.2,
        "speech_sample_rate": 16000,
        "output_audio_codec": "wav",
    }


def test_sarvam_stt_posts_multipart_audio_and_reads_the_transcript() -> None:
    reply = httpx.Response(
        200, json={"request_id": "r2", "transcript": "నమస్కారం", "language_code": "te-IN"}
    )
    text, request = run(SarvamSTT, reply, "transcribe", WAV, "te")
    assert text == "నమస్కారం"
    assert str(request.url) == "https://api.sarvam.ai/speech-to-text"
    assert request.headers["content-type"].startswith("multipart/form-data")
    assert b'name="language_code"' in request.content and b"te-IN" in request.content
    assert b'name="model"' in request.content and b"saaras:v4" in request.content
    assert WAV in request.content


def test_smallest_tts_asks_for_wav_with_the_accept_header() -> None:
    audio, request = run(
        SmallestTTS, httpx.Response(200, content=WAV), "synthesize", "hello", "avery", "en", 1.0
    )
    assert audio == WAV
    assert str(request.url) == "https://api.smallest.ai/waves/v1/tts"
    assert request.headers["authorization"] == "Bearer test-key"
    assert request.headers["accept"] == "audio/wav"
    assert json.loads(request.content) == {
        "text": "hello",
        "voice_id": "avery",
        "model": "lightning_v3.1",
        "sample_rate": 16000,
        "speed": 1.0,
        "language": "en",
        "output_format": "wav",
    }


@pytest.mark.parametrize(("language", "sent"), [("te", "multi-indic"), ("hi", "hi"), ("en", "en")])
def test_smallest_stt_posts_raw_audio_and_reads_the_transcription(language: str, sent: str) -> None:
    reply = httpx.Response(200, json={"status": "success", "transcription": "hello there"})
    text, request = run(SmallestSTT, reply, "transcribe", WAV, language)
    assert text == "hello there"
    assert request.url.path == "/waves/v1/stt/"
    assert dict(request.url.params) == {"model": "pulse", "language": sent}
    assert request.headers["content-type"] == "application/octet-stream"
    assert request.content == WAV


def test_cartesia_tts_bytes_request_uses_bearer_version_and_clamped_speed() -> None:
    audio, request = run(
        CartesiaTTS, httpx.Response(200, content=WAV), "synthesize", "hi", "voice-1", "en", 3.0
    )
    assert audio == WAV
    assert str(request.url) == "https://api.cartesia.ai/tts/bytes"
    assert request.headers["authorization"] == "Bearer test-key"
    assert request.headers["cartesia-version"] == "2026-08-14"
    body = json.loads(request.content)
    assert body["voice"] == {"id": "voice-1"} and body["model_id"] == "sonic-3.6"
    assert body["output_format"] == {
        "container": "wav",
        "encoding": "pcm_s16le",
        "sample_rate": 16000,
    }
    assert body["generation_config"] == {"speed": 1.5}


def test_vobiz_originate_posts_to_the_call_endpoint_with_a_trailing_slash() -> None:
    reply = httpx.Response(
        200, json={"api_id": "a", "message": "Call fired", "request_uuid": "uuid-1"}
    )
    call_id, request = run(
        VobizTelephony,
        reply,
        "originate",
        "+911400000001",
        "+919876543210",
        "https://e.example/vobiz/answer?call=1",
    )
    assert call_id == "uuid-1"
    assert str(request.url) == "https://api.vobiz.ai/api/v1/Account/MA_TEST/Call/"
    assert (
        request.headers["x-auth-id"] == "MA_TEST" and request.headers["x-auth-token"] == "test-key"
    )
    assert json.loads(request.content) == {
        "from": "911400000001",
        "to": "919876543210",
        "answer_url": "https://e.example/vobiz/answer?call=1",
        "answer_method": "POST",
    }


def test_a_vendor_rejection_raises() -> None:
    with pytest.raises(httpx.HTTPStatusError):
        run(
            SarvamTTS,
            httpx.Response(403, json={"error": {"code": "invalid_api_key_error"}}),
            "synthesize",
            "x",
            "shubh",
            "en",
            1.0,
        )
