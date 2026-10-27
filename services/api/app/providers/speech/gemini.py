"""Gemini adapter (Google AI Studio API, header `x-goog-api-key`)."""

import base64
import math
import os
from typing import Any, ClassVar

from app.providers.base import ChatMessage, EmbeddingProvider, FileReader, LLMProvider
from app.providers.speech.common import VendorHealth

BASE = "https://generativelanguage.googleapis.com/v1beta"
# ponytail: Google restricts 2.5 to keys that used it before; AXON_GEMINI_MODEL switches model
# (for example to gemini-3.6-flash) without a code change.
DEFAULT_MODEL = "gemini-2.5-flash"
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMENSIONS = 768  # the model's 3072 is cut down: smaller rows, same ranking in practice
EMBEDDING_BATCH = 100  # most texts one batchEmbedContents call takes


def model() -> str:
    return os.environ.get("AXON_GEMINI_MODEL") or DEFAULT_MODEL


class GeminiLLM(VendorHealth, LLMProvider, FileReader):
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

    async def read_file(self, data: bytes, mime: str, instruction: str) -> str:
        body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode()}},
                        {"text": instruction},
                    ],
                }
            ],
            "generationConfig": {"maxOutputTokens": 8192, "thinkingConfig": {"thinkingBudget": 0}},
        }
        async with self.client() as client:
            response = await client.post(
                f"{BASE}/models/{model()}:generateContent", headers=self.headers(), json=body
            )
            response.raise_for_status()
            parts = response.json()["candidates"][0]["content"]["parts"]
            return "".join(str(p.get("text", "")) for p in parts)


def embedding_model() -> str:
    return os.environ.get("AXON_GEMINI_EMBEDDING_MODEL") or EMBEDDING_MODEL


def unit(vector: list[float]) -> list[float]:
    """Scaled to length 1, so the dot product of two vectors is their cosine. (The vendor only
    returns unit vectors at its full size.)"""
    length = math.sqrt(sum(x * x for x in vector))
    if length == 0:
        raise ValueError("the vendor returned an empty embedding")
    return [x / length for x in vector]


class GeminiEmbedding(VendorHealth, EmbeddingProvider):
    name = "gemini"
    health_url = f"{BASE}/models"
    health_params: ClassVar[dict[str, str] | None] = {"pageSize": "1"}

    def headers(self) -> dict[str, str]:
        return {"x-goog-api-key": os.environ["GEMINI_API_KEY"]}

    async def embed(self, texts: list[str], *, query: bool = False) -> list[list[float]]:
        path, task = (
            f"models/{embedding_model()}",
            "RETRIEVAL_QUERY" if query else "RETRIEVAL_DOCUMENT",
        )
        vectors: list[list[float]] = []
        async with self.client() as client:
            for start in range(0, len(texts), EMBEDDING_BATCH):
                body = {
                    "requests": [
                        {
                            "model": path,
                            "content": {"parts": [{"text": text}]},
                            "taskType": task,
                            "outputDimensionality": EMBEDDING_DIMENSIONS,
                        }
                        for text in texts[start : start + EMBEDDING_BATCH]
                    ]
                }
                response = await client.post(
                    f"{BASE}/{path}:batchEmbedContents", headers=self.headers(), json=body
                )
                response.raise_for_status()
                vectors += [unit(e["values"]) for e in response.json()["embeddings"]]
        if len(vectors) != len(texts):
            raise ValueError("the vendor returned a different number of embeddings than texts")
        return vectors
