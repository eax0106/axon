"""Sarvam adapters: Saaras speech-to-text, Bulbul text-to-speech, Sarvam LLM.

REST base https://api.sarvam.ai, header `api-subscription-key`. Sarvam has no documented
read-only endpoint, so health posts a one-word language-identification request.
"""

import base64
import os
from typing import Any, ClassVar

from app.providers.base import (
    ChatMessage,
    LLMProvider,
    SpeechToTextProvider,
    TextToSpeechProvider,
)
from app.providers.speech.common import VendorHealth, check_language

BASE = "https://api.sarvam.ai"
STT_MODEL = "saaras:v4"
TTS_MODEL, TTS_VOICE = "bulbul:v3", "shubh"
LLM_MODEL = "sarvam-105b"
CODES = {"te": "te-IN", "hi": "hi-IN", "en": "en-IN"}


class _Sarvam(VendorHealth):
    name = "sarvam"
    health_method = "POST"
    health_url = f"{BASE}/text-lid"
    health_json: ClassVar[dict[str, Any] | None] = {"input": "hello"}

    def headers(self) -> dict[str, str]:
        return {"api-subscription-key": os.environ["SARVAM_API_KEY"]}


class SarvamSTT(_Sarvam, SpeechToTextProvider):
    async def transcribe(self, wav: bytes, language: str) -> str:
        async with self.client() as client:
            response = await client.post(
                f"{BASE}/speech-to-text",
                headers=self.headers(),
                files={"file": ("clip.wav", wav, "audio/wav")},
                data={"model": STT_MODEL, "language_code": CODES[check_language(language)]},
            )
            response.raise_for_status()
            return str(response.json()["transcript"])


class SarvamTTS(_Sarvam, TextToSpeechProvider):
    async def synthesize(self, text: str, voice_id: str, language: str, speed: float) -> bytes:
        body = {
            "text": text,
            "language_code": CODES[check_language(language)],
            "model": TTS_MODEL,
            "speaker": voice_id,
            "pace": speed,
            "speech_sample_rate": 16000,
            "output_audio_codec": "wav",
        }
        async with self.client() as client:
            response = await client.post(
                f"{BASE}/text-to-speech", headers=self.headers(), json=body
            )
            response.raise_for_status()
            return base64.b64decode(response.json()["audios"][0])


class SarvamLLM(_Sarvam, LLMProvider):
    async def complete(
        self, system: str, messages: list[ChatMessage], *, json_output: bool = False
    ) -> str:
        body: dict[str, Any] = {
            "model": LLM_MODEL,
            "messages": [{"role": "system", "content": system}, *messages],
            # Sarvam's reasoning tokens count against max_tokens, so leave room for the answer.
            "max_tokens": 4096,
        }
        if json_output:
            body["response_format"] = {"type": "json_object"}
        headers = {**self.headers(), "Authorization": f"Bearer {os.environ['SARVAM_API_KEY']}"}
        async with self.client() as client:
            response = await client.post(f"{BASE}/v1/chat/completions", headers=headers, json=body)
            response.raise_for_status()
            return str(response.json()["choices"][0]["message"]["content"])
