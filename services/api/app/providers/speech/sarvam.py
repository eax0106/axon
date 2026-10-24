"""Sarvam adapters: Saaras speech-to-text, Bulbul text-to-speech, Sarvam LLM.

REST base https://api.sarvam.ai, header `api-subscription-key`. Sarvam has no documented
read-only endpoint, so health posts a one-word language-identification request.
"""

import os
from typing import Any, ClassVar

from app.providers.base import LLMProvider, SpeechToTextProvider, TextToSpeechProvider
from app.providers.speech.common import VendorHealth


class _Sarvam(VendorHealth):
    name = "sarvam"
    health_method = "POST"
    health_url = "https://api.sarvam.ai/text-lid"
    health_json: ClassVar[dict[str, Any] | None] = {"input": "hello"}

    def headers(self) -> dict[str, str]:
        return {"api-subscription-key": os.environ["SARVAM_API_KEY"]}


class SarvamSTT(_Sarvam, SpeechToTextProvider):
    pass


class SarvamTTS(_Sarvam, TextToSpeechProvider):
    pass


class SarvamLLM(_Sarvam, LLMProvider):
    pass
