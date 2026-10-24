"""Gemini adapter (Google AI Studio API, header `x-goog-api-key`)."""

import os
from typing import ClassVar

from app.providers.base import LLMProvider
from app.providers.speech.common import VendorHealth


class GeminiLLM(VendorHealth, LLMProvider):
    name = "gemini"
    health_url = "https://generativelanguage.googleapis.com/v1beta/models"
    health_params: ClassVar[dict[str, str] | None] = {"pageSize": "1"}

    def headers(self) -> dict[str, str]:
        return {"x-goog-api-key": os.environ["GEMINI_API_KEY"]}
