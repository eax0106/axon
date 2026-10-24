"""Cartesia adapter: Sonic text-to-speech (Premium tier).

REST base https://api.cartesia.ai, header `Authorization: Bearer <key>` and `Cartesia-Version`.
"""

import os
from typing import ClassVar

from app.providers.base import TextToSpeechProvider
from app.providers.speech.common import VendorHealth, check_language

BASE = "https://api.cartesia.ai"
MODEL = "sonic-3.6"
API_VERSION = "2026-08-14"
# Cartesia documents English voice ids only; Hindi and Telugu voices are picked from the voice
# library (play.cartesia.ai/voices) and set in these variables.
VOICE_ENV = {"hi": "CARTESIA_VOICE_HI", "te": "CARTESIA_VOICE_TE"}


class CartesiaTTS(VendorHealth, TextToSpeechProvider):
    name = "cartesia"
    health_url = f"{BASE}/voices"
    health_params: ClassVar[dict[str, str] | None] = {"limit": "1"}

    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {os.environ['CARTESIA_API_KEY']}",
            "Cartesia-Version": API_VERSION,
        }

    async def health(self) -> None:
        # A key alone is not enough: without a Hindi or Telugu voice those calls would 503.
        missing = [var for var in VOICE_ENV.values() if not os.environ.get(var)]
        if missing:
            raise RuntimeError(f"set {', '.join(missing)} (voice ids from play.cartesia.ai/voices)")
        await super().health()

    async def synthesize(self, text: str, voice_id: str, language: str, speed: float) -> bytes:
        body = {
            "model_id": MODEL,
            "transcript": text,
            "voice": {"id": voice_id},
            "language": check_language(language),
            "output_format": {"container": "wav", "encoding": "pcm_s16le", "sample_rate": 16000},
            # Cartesia accepts 0.6 to 1.5.
            "generation_config": {"speed": min(1.5, max(0.6, speed))},
        }
        async with self.client() as client:
            response = await client.post(f"{BASE}/tts/bytes", headers=self.headers(), json=body)
            response.raise_for_status()
            return response.content
