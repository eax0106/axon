"""Smallest AI adapters: Pulse speech-to-text and Lightning v3.1 text-to-speech.

REST base https://api.smallest.ai/waves/v1, header `Authorization: Bearer <key>`.
"""

import os

from app.providers.base import SpeechToTextProvider, TextToSpeechProvider
from app.providers.speech.common import VendorHealth


class _Smallest(VendorHealth):
    name = "smallest"
    health_url = "https://api.smallest.ai/waves/v1/lightning-v3.1/get_voices"

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {os.environ['SMALLEST_API_KEY']}"}


class SmallestSTT(_Smallest, SpeechToTextProvider):
    pass


class SmallestTTS(_Smallest, TextToSpeechProvider):
    pass
