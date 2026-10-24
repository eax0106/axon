"""Cartesia adapter: Sonic text-to-speech (Premium tier).

REST base https://api.cartesia.ai, header `Authorization: Bearer <key>` and `Cartesia-Version`.
"""

import os
from typing import TYPE_CHECKING, ClassVar

from app.providers.base import TextToSpeechProvider
from app.providers.speech.common import VendorHealth, need_env, pipecat_language

if TYPE_CHECKING:
    from pipecat.processors.frame_processor import FrameProcessor

MODEL = "sonic-3.6"
API_VERSION = "2026-08-14"
# Cartesia documents English voice ids only; Hindi and Telugu voices are picked from the voice
# library (play.cartesia.ai/voices) and set in CARTESIA_VOICE_HI / CARTESIA_VOICE_TE.
ENGLISH_VOICE = "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4"


class CartesiaTTS(VendorHealth, TextToSpeechProvider):
    name = "cartesia"
    health_url = "https://api.cartesia.ai/voices"
    health_params: ClassVar[dict[str, str] | None] = {"limit": "1"}

    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {os.environ['CARTESIA_API_KEY']}",
            "Cartesia-Version": API_VERSION,
        }

    def voice(self, language: str) -> str:
        if pipecat_language(language).value == "en":
            return os.environ.get("CARTESIA_VOICE_EN") or ENGLISH_VOICE
        return need_env(self, f"CARTESIA_VOICE_{language.upper()}")

    def pipecat_service(self, language: str) -> "FrameProcessor":
        from pipecat.services.cartesia.tts import CartesiaTTSService

        return CartesiaTTSService(
            api_key=os.environ["CARTESIA_API_KEY"],
            settings=CartesiaTTSService.Settings(
                model=MODEL, voice=self.voice(language), language=pipecat_language(language)
            ),
        )
