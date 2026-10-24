"""Gemini adapter (Google AI Studio API, header `x-goog-api-key`)."""

import os
from typing import Any, ClassVar

from app.providers.base import ChatMessage, LLMProvider
from app.providers.speech.common import VendorHealth

BASE = "https://generativelanguage.googleapis.com/v1beta"
# ponytail: Google restricts 2.5 to keys that used it before; AXON_GEMINI_MODEL switches model
# (for example to gemini-3.6-flash) without a code change.
DEFAULT_MODEL = "gemini-2.5-flash"


def model() -> str:
    return os.environ.get("AXON_GEMINI_MODEL") or DEFAULT_MODEL


class GeminiLLM(VendorHealth, LLMProvider):
    name = "gemini"
    health_url = f"{BASE}/models"
    health_params: ClassVar[dict[str, str] | None] = {"pageSize": "1"}

    def headers(self) -> dict[str, str]:
        return {"x-goog-api-key": os.environ["GEMINI_API_KEY"]}

    async def complete(
        self, system: str, messages: list[ChatMessage], *, json_output: bool = False
    ) -> str:
        config: dict[str, Any] = {
            "maxOutputTokens": 4096,
            "thinkingConfig": {"thinkingBudget": 0},  # drafting does not need hidden reasoning
        }
        if json_output:
            config["responseMimeType"] = "application/json"
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [
                {
                    "role": "model" if m["role"] == "assistant" else "user",
                    "parts": [{"text": m["content"]}],
                }
                for m in messages
            ],
            "generationConfig": config,
        }
        async with self.client() as client:
            response = await client.post(
                f"{BASE}/models/{model()}:generateContent", headers=self.headers(), json=body
            )
            response.raise_for_status()
            return str(response.json()["candidates"][0]["content"]["parts"][0]["text"])
