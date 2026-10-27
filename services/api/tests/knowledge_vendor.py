"""A stand-in for Gemini and Sarvam in the training tests: it answers over HTTP, so the real
adapters run. Embeddings are a bag of words (with a few synonyms) hashed into 768 slots, which is
enough for "close in meaning" to be decided by shared words in these tests only."""

import json
import re
import zlib
from typing import Any

import httpx

DIM = 768
STOP = {
    "a", "an", "the", "is", "are", "of", "to", "do", "does", "you", "your", "what", "how", "i",
    "in", "for", "and", "it", "on", "at", "can", "we", "our", "my", "me", "with", "or", "be",
}  # fmt: skip
SYNONYMS = {
    "cost": "price", "costs": "price", "much": "price", "rupees": "price", "fee": "price",
    "charge": "price", "plans": "plan",
}  # fmt: skip


def vector(text: str) -> list[float]:
    slots = [0.0] * DIM
    for word in re.findall(r"\w+", text.lower()):
        word = SYNONYMS.get(word, word)
        if word not in STOP:
            slots[zlib.crc32(word.encode()) % DIM] += 1.0
    return slots


class Vendor:
    """Gemini (chat, file reading, embeddings) and Sarvam (speech to text) with canned answers."""

    def __init__(self) -> None:
        self.chat = '{"items": []}'
        self.file_text = "NONE"
        self.finish = "STOP"  # "MAX_TOKENS" is a reply the model cut short
        self.heard = "  we close at six  "
        self.status = 200
        self.embed_status = 200
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "api.sarvam.ai":
            return httpx.Response(200, json={"request_id": "r", "transcript": self.heard})
        if request.url.path.endswith(":batchEmbedContents"):
            if self.embed_status != 200:
                return httpx.Response(self.embed_status, json={})
            requests = json.loads(request.content)["requests"]
            values = [
                {"values": vector(r["content"]["parts"][0]["text"]) or [1.0]} for r in requests
            ]
            return httpx.Response(200, json={"embeddings": values})
        sent = json.loads(request.content)
        reading = any("inlineData" in p for p in sent["contents"][0]["parts"])
        text = self.file_text if reading else self.chat
        content = {"role": "model", "parts": [{"text": text}]}
        payload = {"candidates": [{"content": content, "finishReason": self.finish}]}
        return httpx.Response(self.status, json=payload)

    def sent(self, suffix: str) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests if r.url.path.endswith(suffix)]


def hire(api: Any, headers: dict[str, str], channel: str = "instant") -> str:
    response = api.post("/employees", json={"channel": channel, "name": "Asha"}, headers=headers)
    return str(response.json()["id"])
