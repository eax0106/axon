"""Smallest AI adapters: Pulse speech-to-text and Lightning v3.1 text-to-speech.

REST base https://api.smallest.ai/waves/v1, header `Authorization: Bearer <key>`.
"""

import os
from typing import TYPE_CHECKING

from app.providers.base import SpeechToTextProvider, TextToSpeechProvider
from app.providers.speech.common import VendorHealth, check_language, pipecat_language

if TYPE_CHECKING:
    from pipecat.processors.frame_processor import FrameProcessor

TTS_MODEL = "lightning_v3.1"
# Voices from Smallest's voice catalog that speak each V1 language.
VOICES = {"te": "srihari", "hi": "devansh", "en": "avery"}


class _Smallest(VendorHealth):
    name = "smallest"
    health_url = "https://api.smallest.ai/waves/v1/lightning-v3.1/get_voices"

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {os.environ['SMALLEST_API_KEY']}"}


class SmallestSTT(_Smallest, SpeechToTextProvider):
    def pipecat_service(self, language: str) -> "FrameProcessor":
        from pipecat.services.smallest.stt import SmallestSTTService

        return SmallestSTTService(
            api_key=os.environ["SMALLEST_API_KEY"],
            settings=SmallestSTTService.Settings(language=pipecat_language(language)),
        )


class SmallestTTS(_Smallest, TextToSpeechProvider):
    def pipecat_service(self, language: str) -> "FrameProcessor":
        from pipecat.services.smallest.tts import SmallestTTSService

        return SmallestTTSService(
            api_key=os.environ["SMALLEST_API_KEY"],
            settings=SmallestTTSService.Settings(
                model=TTS_MODEL,
                voice=VOICES[check_language(language)],
                language=pipecat_language(language),
            ),
        )
