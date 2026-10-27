"""Documents an employee can look things up in: upload, cut, embed, store, remove."""

import base64
from typing import Any

import pytest
from fastapi.testclient import TestClient

from .conftest import sql
from .helpers import seed, signup
from .knowledge_vendor import DIM, Vendor, hire


@pytest.fixture
def api(db_client: TestClient, migrated_url: str) -> TestClient:
    seed(migrated_url)
    return db_client


def upload(
    api: TestClient,
    owner: dict[str, str],
    employee: str,
    body: bytes,
    mime: str = "text/plain",
    name: str = "menu",
) -> Any:
    return api.post(
        f"/employees/{employee}/training/documents",
        params={"name": name},
        content=body,
        headers={**owner, "Content-Type": mime},
    )


def test_a_text_document_becomes_embedded_passages(
    api: TestClient, teaching: Vendor, migrated_url: str
) -> None:
    owner = signup(api)
    employee = hire(api, owner)
    response = upload(api, owner, employee, b"Tea costs 20 rupees. Coffee costs 30 rupees.")
    assert response.status_code == 201
    doc = response.json()
    assert doc["name"] == "menu" and doc["chars"] == 44
    listed = api.get(f"/employees/{employee}/training", headers=owner).json()["documents"]
    assert [d["id"] for d in listed] == [doc["id"]]
    sent = teaching.sent(":batchEmbedContents")[0]["requests"][0]
    assert sent["taskType"] == "RETRIEVAL_DOCUMENT" and sent["outputDimensionality"] == DIM
    assert sent["model"] == "models/gemini-embedding-001"
    stored = sql(
        migrated_url,
        "SELECT count(*) FROM knowledge_chunks WHERE cardinality(embedding) = :d"
        " AND abs((SELECT sum(x * x) FROM unnest(embedding) AS t(x)) - 1) < 0.001",
        {"d": DIM},
    )
    assert stored == 1  # one passage, 768 numbers, unit length
    assert teaching.requests[-1].headers["x-goog-api-key"] == "test-key"
    # Documents are free apart from the hourly allowance.
    assert api.get("/wallet", headers=owner).json()["balance"] == "50.0000"


def test_a_long_document_is_embedded_in_batches_of_a_hundred(
    api: TestClient, teaching: Vendor, migrated_url: str
) -> None:
    owner = signup(api)
    employee = hire(api, owner)
    text = "\n".join(f"Line {n} " + "word " * 80 for n in range(110))
    assert upload(api, owner, employee, text.encode()).status_code == 201
    sizes = [len(r["requests"]) for r in teaching.sent(":batchEmbedContents")]
    assert sizes == [100, 10]
    assert sql(migrated_url, "SELECT count(*) FROM knowledge_chunks") == 110


def test_markdown_csv_pdf_and_photos_are_read(api: TestClient, teaching: Vendor) -> None:
    owner = signup(api)
    employee = hire(api, owner)
    assert upload(api, owner, employee, b"# Menu\n- Tea 20", "text/markdown").status_code == 201
    assert upload(api, owner, employee, b"item,price\ntea,20", "text/csv").status_code == 201
    teaching.file_text = "Haircut 200 rupees\nShave 100 rupees"
    for mime, raw in (("application/pdf", b"%PDF-1.7 x"), ("image/jpeg", b"\xff\xd8\xff")):
        assert upload(api, owner, employee, raw, mime).status_code == 201
        part = teaching.sent(":generateContent")[-1]["contents"][0]["parts"][0]["inlineData"]
        assert part == {"mimeType": mime, "data": base64.b64encode(raw).decode()}
    assert len(api.get(f"/employees/{employee}/training", headers=owner).json()["documents"]) == 4


def test_what_cannot_be_used_is_refused_and_stores_nothing(
    api: TestClient, teaching: Vendor, migrated_url: str
) -> None:
    owner = signup(api)
    employee = hire(api, owner)

    def refused(body: bytes, mime: str, status: int) -> None:
        assert upload(api, owner, employee, body, mime).status_code == status, mime

    refused(b"x", "application/zip", 415)
    refused(b"\xff\xfe\x00bad", "text/plain", 422)  # not UTF-8
    refused(b"", "text/plain", 422)
    refused(b" \n ", "text/plain", 422)
    refused(("word " * 12_100).encode(), "text/plain", 422)  # over 60,000 characters
    refused(bytes(200_001), "text/plain", 413)
    teaching.file_text = "NONE"
    refused(b"%PDF", "application/pdf", 422)  # nothing readable
    assert (
        api.post(  # a name is required
            f"/employees/{employee}/training/documents",
            content=b"x",
            headers={**owner, "Content-Type": "text/plain"},
        ).status_code
        == 422
    )
    assert sql(migrated_url, "SELECT count(*) FROM knowledge_docs") == 0


def test_a_failed_embedding_stores_nothing(
    api: TestClient, teaching: Vendor, migrated_url: str
) -> None:
    owner = signup(api)
    employee = hire(api, owner)
    teaching.embed_status = 500
    response = upload(api, owner, employee, b"Tea costs 20 rupees.")
    assert response.status_code == 502
    assert response.json()["error"] == "provider_error"
    assert sql(migrated_url, "SELECT count(*) FROM knowledge_docs") == 0
    assert sql(migrated_url, "SELECT count(*) FROM knowledge_chunks") == 0


def test_ten_documents_at_most(api: TestClient, teaching: Vendor) -> None:
    owner = signup(api)
    employee = hire(api, owner)
    for n in range(10):
        assert upload(api, owner, employee, f"Doc {n}".encode(), name=f"d{n}").status_code == 201
    over = upload(api, owner, employee, b"one more", name="eleven")
    assert over.status_code == 409


def test_deleting_a_document_removes_its_passages(
    api: TestClient, teaching: Vendor, migrated_url: str
) -> None:
    owner, other = signup(api), signup(api, "b@example.com", "B")
    employee = hire(api, owner)
    doc = upload(api, owner, employee, b"Tea costs 20 rupees.").json()["id"]
    path = f"/employees/{employee}/training/documents/{doc}"
    assert api.delete(path, headers=other).status_code == 404
    assert sql(migrated_url, "SELECT count(*) FROM knowledge_chunks") == 1
    assert api.delete(path, headers=owner).status_code == 204
    assert sql(migrated_url, "SELECT count(*) FROM knowledge_chunks") == 0
    assert api.delete(path, headers=owner).status_code == 404


def test_documents_are_the_accounts_own(api: TestClient, teaching: Vendor) -> None:
    owner, other = signup(api), signup(api, "b@example.com", "B")
    employee = hire(api, owner)
    assert upload(api, other, employee, b"x").status_code == 404


def test_start_over_removes_documents_and_their_passages(
    api: TestClient, teaching: Vendor, migrated_url: str
) -> None:
    owner = signup(api)
    employee = hire(api, owner)
    upload(api, owner, employee, b"Tea costs 20 rupees.")
    api.post(f"/employees/{employee}/reset", headers=owner)
    assert sql(migrated_url, "SELECT count(*) FROM knowledge_docs") == 0
    assert sql(migrated_url, "SELECT count(*) FROM knowledge_chunks") == 0
