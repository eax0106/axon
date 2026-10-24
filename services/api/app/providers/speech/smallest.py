"""Smallest AI adapters: Pulse speech-to-text and Lightning v3.1 text-to-speech.

REST base https://api.smallest.ai/waves/v1, header `Authorization: Bearer <key>`.
"""

import os

from app.providers.base import SpeechToTextProvider, TextToSpeechProvider
from app.providers.speech.common import VendorHealth, check_language

BASE = "https://api.smallest.ai/waves/v1"
TTS_MODEL = "lightning_v3.1"
# Pulse lists en and hi; Telugu is only documented through its Indic auto-detect.
# ponytail: confirm `te` against the real API in the contract test, then pass it directly.
STT_LANGUAGE = {"te": "multi-indic", "hi": "hi", "en": "en"}


class _Smallest(VendorHealth):
    name = "smallest"
    health_url = f"{BASE}/lightning-v3.1/get_voices"

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {os.environ['SMALLEST_API_KEY']}"}


class SmallestSTT(_Smallest, SpeechToTextProvider):
    async def transcribe(self, wav: bytes, language: str) -> str:
        params = {"model": "pulse", "language": STT_LANGUAGE[check_language(language)]}
        headers = {**self.headers(), "Content-Type": "application/octet-stream"}
        async with self.client() as client:
            response = await client.post(
                f"{BASE}/stt/", headers=headers, params=params, content=wav
            )
            response.raise_for_status()
            return str(response.json()["transcription"])


class SmallestTTS(_Smallest, TextToSpeechProvider):
    async def synthesize(self, text: str, voice_id: str, language: str, speed: float) -> bytes:
        body = {
            "text": text,
            "voice_id": voice_id,
            "model": TTS_MODEL,
            "sample_rate": 16000,
            "speed": speed,
            "language": check_language(language),
            "output_format": "wav",
        }
        headers = {**self.headers(), "Accept": "audio/wav"}
        async with self.client() as client:
            response = await client.post(f"{BASE}/tts", headers=headers, json=body)
            response.raise_for_status()
            return response.content
