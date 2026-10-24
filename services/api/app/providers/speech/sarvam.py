"""Sarvam adapters: Saaras speech-to-text (codemix), Bulbul text-to-speech, Sarvam LLM.

REST base https://api.sarvam.ai, header `api-subscription-key`. Sarvam has no documented
read-only endpoint, so health posts a one-word language-identification request.
"""

import os
from typing import TYPE_CHECKING, Any, ClassVar

from app.providers.base import LLMProvider, SpeechToTextProvider, TextToSpeechProvider
from app.providers.speech.common import VendorHealth, pipecat_language

if TYPE_CHECKING:
    from pipecat.processors.frame_processor import FrameProcessor

STT_MODEL = "saaras:v4"
TTS_MODEL = "bulbul:v3"
TTS_VOICE = "shubh"
LLM_MODEL = "sarvam-105b"


class _Sarvam(VendorHealth):
    name = "sarvam"
    health_method = "POST"
    health_url = "https://api.sarvam.ai/text-lid"
    health_json: ClassVar[dict[str, Any] | None] = {"input": "hello"}

    def headers(self) -> dict[str, str]:
        return {"api-subscription-key": os.environ["SARVAM_API_KEY"]}


class SarvamSTT(_Sarvam, SpeechToTextProvider):
    def pipecat_service(self, language: str) -> "FrameProcessor":
        from pipecat.services.sarvam.stt import SarvamSTTService

        return SarvamSTTService(
            api_key=os.environ["SARVAM_API_KEY"],
            mode="codemix",
            settings=SarvamSTTService.Settings(
                model=STT_MODEL, language=pipecat_language(language)
            ),
        )


class SarvamTTS(_Sarvam, TextToSpeechProvider):
    def pipecat_service(self, language: str) -> "FrameProcessor":
        from pipecat.services.sarvam.tts import SarvamTTSService

        return SarvamTTSService(
            api_key=os.environ["SARVAM_API_KEY"],
            settings=SarvamTTSService.Settings(
                model=TTS_MODEL, voice=TTS_VOICE, language=pipecat_language(language)
            ),
        )


class SarvamLLM(_Sarvam, LLMProvider):
    def pipecat_service(self, language: str) -> "FrameProcessor":
        from pipecat.services.sarvam.llm import SarvamLLMService

        pipecat_language(language)  # reject languages outside V1
        # ponytail: Sarvam's reasoning counts against max tokens, so keep the cap at 1500 or more.
        return SarvamLLMService(
            api_key=os.environ["SARVAM_API_KEY"],
            settings=SarvamLLMService.Settings(model=LLM_MODEL, max_tokens=1500),
        )
