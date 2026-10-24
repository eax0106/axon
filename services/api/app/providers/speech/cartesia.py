"""Cartesia adapter: Sonic text-to-speech (Premium tier).

REST base https://api.cartesia.ai, header `Authorization: Bearer <key>` and `Cartesia-Version`.
"""

import os
from typing import ClassVar

from app.providers.base import TextToSpeechProvider
from app.providers.speech.common import VendorHealth

API_VERSION = "2026-08-14"
# Cartesia documents English voice ids only; Hindi and Telugu voices are picked from the voice
# library (play.cartesia.ai/voices) and set in these variables.
VOICE_ENV = {"hi": "CARTESIA_VOICE_HI", "te": "CARTESIA_VOICE_TE"}


class CartesiaTTS(VendorHealth, TextToSpeechProvider):
    name = "cartesia"
    health_url = "https://api.cartesia.ai/voices"
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
