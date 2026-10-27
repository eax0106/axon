"""The Gemini embedding and file-reading adapters send the vendor's documented requests."""

import asyncio
import base64
import json
import math

import httpx
import pytest

from app.providers.base import EmbeddingProvider, FileReader, ProviderKind
from app.providers.registry import ADAPTERS, VENDOR_KEYS, report_all, require
from app.providers.speech.gemini import EMBEDDING_DIMENSIONS, GeminiEmbedding, GeminiLLM, unit

URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:batchEmbedContents"


class Vendor:
    def __init__(self, width: int = 4, short: bool = False) -> None:
        self.requests: list[httpx.Request] = []
        self.width, self.short = width, short

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        asked = json.loads(request.content)["requests"]
        count = len(asked) - 1 if self.short else len(asked)
        return httpx.Response(
            200, json={"embeddings": [{"values": [3.0] + [4.0] * (self.width - 1)}] * count}
        )


def embedding(fake: Vendor) -> GeminiEmbedding:
    return GeminiEmbedding(httpx.MockTransport(fake.handler))


def test_the_request_is_the_documented_batch_embed_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "k-1")
    fake = Vendor()
    asyncio.run(embedding(fake).embed(["tea costs 20", "coffee costs 30"]))
    [request] = fake.requests
    assert request.method == "POST" and str(request.url) == URL
    assert request.headers["x-goog-api-key"] == "k-1"
    assert json.loads(request.content) == {
        "requests": [
            {
                "model": "models/gemini-embedding-001",
                "content": {"parts": [{"text": text}]},
                "taskType": "RETRIEVAL_DOCUMENT",
                "outputDimensionality": EMBEDDING_DIMENSIONS,
            }
            for text in ("tea costs 20", "coffee costs 30")
        ]
    }


def test_a_question_is_embedded_as_a_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "k-1")
    fake = Vendor()
    asyncio.run(embedding(fake).embed(["how much is tea"], query=True))
    assert json.loads(fake.requests[0].content)["requests"][0]["taskType"] == "RETRIEVAL_QUERY"


def test_the_model_can_be_changed_without_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "k-1")
    monkeypatch.setenv("AXON_GEMINI_EMBEDDING_MODEL", "gemini-embedding-002")
    fake = Vendor()
    asyncio.run(embedding(fake).embed(["x"]))
    assert str(fake.requests[0].url).endswith("models/gemini-embedding-002:batchEmbedContents")
    assert json.loads(fake.requests[0].content)["requests"][0]["model"] == (
        "models/gemini-embedding-002"
    )


def test_more_than_a_hundred_texts_go_in_batches_and_keep_their_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "k-1")
    fake = Vendor()
    vectors = asyncio.run(embedding(fake).embed([f"t{n}" for n in range(250)]))
    assert [len(json.loads(r.content)["requests"]) for r in fake.requests] == [100, 100, 50]
    assert len(vectors) == 250


def test_vectors_come_back_at_unit_length(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "k-1")
    [vector] = asyncio.run(embedding(Vendor()).embed(["x"]))
    assert math.isclose(math.fsum(x * x for x in vector), 1.0) and len(vector) == 4
    assert unit([0.0, 5.0]) == [0.0, 1.0]
    with pytest.raises(ValueError, match="empty embedding"):
        unit([0.0, 0.0])


def test_a_wrong_count_or_a_vendor_refusal_is_an_error_not_a_guess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "k-1")
    with pytest.raises(ValueError, match="different number"):
        asyncio.run(embedding(Vendor(short=True)).embed(["a", "b"]))
    refusing = GeminiEmbedding(httpx.MockTransport(lambda r: httpx.Response(403, json={})))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(refusing.embed(["a"]))


def test_a_file_is_sent_inline_with_the_instruction(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "k-1")
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        parts = [{"text": "Tea 20"}, {"text": "\nCoffee 30"}]
        return httpx.Response(200, json={"candidates": [{"content": {"parts": parts}}]})

    reader = GeminiLLM(httpx.MockTransport(answer))
    raw = b"%PDF-1.7"
    text = asyncio.run(reader.read_file(raw, "application/pdf", "Write it out."))
    assert text == "Tea 20\nCoffee 30"
    assert seen[0].url.path.endswith(":generateContent")
    [content] = json.loads(seen[0].content)["contents"]
    assert content["parts"] == [
        {
            "inlineData": {
                "mimeType": "application/pdf",
                "data": base64.b64encode(b"%PDF-1.7").decode(),
            }
        },
        {"text": "Write it out."},
    ]


def test_the_registry_knows_the_embedding_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    assert ADAPTERS[(ProviderKind.EMBEDDING, "gemini")] is GeminiEmbedding
    assert VENDOR_KEYS[ProviderKind.EMBEDDING] == {"gemini": ("GEMINI_API_KEY",)}
    assert issubclass(GeminiEmbedding, EmbeddingProvider) and issubclass(GeminiLLM, FileReader)
    monkeypatch.setenv("GEMINI_API_KEY", "k-1")
    assert isinstance(require(ProviderKind.EMBEDDING), GeminiEmbedding)
    monkeypatch.delenv("GEMINI_API_KEY")
    rows = asyncio.run(report_all())
    [row] = [r for r in rows if r.kind is ProviderKind.EMBEDDING]
    assert (row.name, row.status, row.missing_keys) == ("gemini", "missing_key", ["GEMINI_API_KEY"])
