"""Retrieval: only passages that are relevant, best first, from this employee's own documents."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from .conftest import sql
from .helpers import seed, signup
from .knowledge_vendor import Vendor, hire


@pytest.fixture
def api(db_client: TestClient, migrated_url: str) -> TestClient:
    seed(migrated_url)
    return db_client


PRICES = {
    "premium": "Premium plan costs 4999 rupees a month.",
    "basic": "Basic plan costs 999 rupees a month.",
    "delivery": "We deliver only within Hyderabad.",
}


def teach(api: TestClient, owner: dict[str, str], employee: str, docs: dict[str, str]) -> None:
    for name, text in docs.items():
        response = api.post(
            f"/employees/{employee}/training/documents",
            params={"name": name},
            content=text.encode(),
            headers={**owner, "Content-Type": "text/plain"},
        )
        assert response.status_code == 201


def ask(api: TestClient, owner: dict[str, str], employee: str, question: str) -> list[Any]:
    response = api.post(
        f"/employees/{employee}/training/documents/search",
        json={"question": question},
        headers=owner,
    )
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


def test_the_relevant_passages_come_back_best_first(api: TestClient, teaching: Vendor) -> None:
    owner = signup(api)
    employee = hire(api, owner)
    teach(api, owner, employee, PRICES)
    found = ask(api, owner, employee, "How much does the premium plan cost?")
    assert [f["document"] for f in found] == ["premium", "basic"]
    assert found[0]["text"] == PRICES["premium"]
    assert found[0]["score"] > found[1]["score"] >= 0.55
    asked = teaching.sent(":batchEmbedContents")[-1]["requests"][0]
    assert asked["taskType"] == "RETRIEVAL_QUERY"


def test_a_question_the_documents_do_not_cover_finds_nothing(
    api: TestClient, teaching: Vendor
) -> None:
    owner = signup(api)
    employee = hire(api, owner)
    teach(api, owner, employee, PRICES)
    assert ask(api, owner, employee, "Do you repair bicycles?") == []
    assert ask(api, owner, employee, "Which colours does the helmet come in?") == []


def test_at_most_three_passages(api: TestClient, teaching: Vendor) -> None:
    owner = signup(api)
    employee = hire(api, owner)
    teach(
        api,
        owner,
        employee,
        {f"plan{n}": f"Plan {n} costs {n}00 rupees a month." for n in range(6)},
    )
    assert len(ask(api, owner, employee, "What does a plan cost?")) == 3


def test_only_this_employees_documents_are_searched(api: TestClient, teaching: Vendor) -> None:
    owner, other = signup(api), signup(api, "b@example.com", "B")
    mine, sibling = hire(api, owner), hire(api, owner)
    stranger = hire(api, other)
    teach(api, owner, mine, PRICES)
    question = "premium plan price"
    assert len(ask(api, owner, mine, question)) == 2
    assert ask(api, owner, sibling, question) == []  # the same account, another employee
    assert ask(api, other, stranger, question) == []
    assert (
        api.post(
            f"/employees/{mine}/training/documents/search",
            json={"question": question},
            headers=other,
        ).status_code
        == 404
    )


def test_passages_embedded_at_another_size_are_skipped_not_an_error(
    api: TestClient, teaching: Vendor, migrated_url: str
) -> None:
    owner = signup(api)
    employee = hire(api, owner)
    teach(api, owner, employee, {"premium": PRICES["premium"]})
    doc = sql(migrated_url, "SELECT id FROM knowledge_docs")
    sql(
        migrated_url,
        "INSERT INTO knowledge_chunks (doc_id, employee_id, position, text, embedding)"
        " SELECT :d, employee_id, 9, 'old model passage', ARRAY[1.0, 0.0, 0.0]::real[]"
        " FROM knowledge_docs WHERE id = :d",
        {"d": doc},
    )
    found = ask(api, owner, employee, "premium plan price")
    assert [f["text"] for f in found] == [PRICES["premium"]]
