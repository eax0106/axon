"""Gemini adapter (Google AI Studio API, header `x-goog-api-key`)."""

import os
from typing import TYPE_CHECKING, ClassVar

from app.providers.base import LLMProvider
from app.providers.speech.common import VendorHealth, check_language

if TYPE_CHECKING:
    from pipecat.processors.frame_processor import FrameProcessor

# ponytail: Google restricts 2.5 to keys that used it before; AXON_GEMINI_MODEL switches model
# (for example to gemini-3.6-flash) without a code change.
DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiLLM(VendorHealth, LLMProvider):
    name = "gemini"
    health_url = "https://generativelanguage.googleapis.com/v1beta/models"
    health_params: ClassVar[dict[str, str] | None] = {"pageSize": "1"}

    def headers(self) -> dict[str, str]:
        return {"x-goog-api-key": os.environ["GEMINI_API_KEY"]}

    def pipecat_service(self, language: str) -> "FrameProcessor":
        from pipecat.services.google.llm import GoogleLLMService

        check_language(language)
        return GoogleLLMService(
            api_key=os.environ["GEMINI_API_KEY"],
            settings=GoogleLLMService.Settings(
                model=os.environ.get("AXON_GEMINI_MODEL") or DEFAULT_MODEL
            ),
        )
