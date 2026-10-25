import csv
import io
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from .conftest import sql
from .helpers import add_call, add_lead, live_employee, seed, signup

T0 = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)


@pytest.fixture
def api(db_client: TestClient, migrated_url: str) -> TestClient:
    seed(migrated_url)
    return db_client


def world(api: TestClient, url: str) -> tuple[dict[str, str], dict[str, Any]]:
    owner = signup(api)
    asha = live_employee(api, url, owner)
    ravi = live_employee(api, url, owner, channel="bulk", number="+911400000002")
    account = sql(url, "SELECT account_id FROM employees LIMIT 1")
    leads = {
        "a": add_lead(url, account, "+919876543210", "Ravi", budget="5 lakh", city="Pune"),
        "b": add_lead(url, account, "+919876543211", "Sita", budget="2 lakh"),
        "c": add_lead(url, account, "+919876543212", None),
    }
    # Lead a: two calls on two channels (one lead across channels); the LATEST decides the column.
    add_call(
        url, account, asha, leads["a"], outcome="not_interested", created_at=T0, summary="first"
    )
    add_call(
        url,
        account,
        ravi,
        leads["a"],
        channel="bulk",
        outcome="interested",
        created_at=T0 + timedelta(days=1),
        summary="second",
    )
    add_call(url, account, asha, leads["b"], outcome="not_interested", created_at=T0)
    add_call(
        url,
        account,
        asha,
        leads["a"],
        is_test=True,
        outcome="other",
        created_at=T0 + timedelta(days=9),
    )
    return owner, {
        "asha": asha,
        "ravi": ravi,
        "account": account,
        "leads": {k: str(v) for k, v in leads.items()},
    }


def test_there_is_one_row_per_phone_with_its_latest_outcome_and_call_count(
    api: TestClient, migrated_url: str
) -> None:
    owner, _w = world(api, migrated_url)
    body = api.get("/leads", headers=owner).json()
    assert body["total"] == 3
    by_phone = {i["phone"]: i for i in body["items"]}
    a = by_phone["+919876543210"]
    assert (a["last_outcome"], a["calls"], a["name"]) == (
        "interested",
        2,
        "Ravi",
    )  # the test call is not counted
    assert a["fields"] == {"budget": "5 lakh", "city": "Pune"}
    assert (
        by_phone["+919876543212"]["last_outcome"] is None
        and by_phone["+919876543212"]["calls"] == 0
    )


@pytest.mark.parametrize(
    ("query", "phones"),
    [
        ("q=Sita", ["+919876543211"]),
        ("q=43212", ["+919876543212"]),
        ("outcome=interested", ["+919876543210"]),
        ("outcome=not_interested", ["+919876543211"]),
        ("outcome=no_outcome", ["+919876543212"]),
    ],
)
def test_search_and_outcome_filters(
    api: TestClient, migrated_url: str, query: str, phones: list[str]
) -> None:
    owner, _ = world(api, migrated_url)
    got = [i["phone"] for i in api.get(f"/leads?{query}", headers=owner).json()["items"]]
    assert got == phones


def test_filter_by_the_employee_who_called(api: TestClient, migrated_url: str) -> None:
    owner, w = world(api, migrated_url)
    ravi = [
        i["phone"]
        for i in api.get(f"/leads?employee_id={w['ravi']}", headers=owner).json()["items"]
    ]
    assert ravi == ["+919876543210"]
    assert api.get("/leads?limit=0", headers=owner).status_code == 422


def test_the_board_groups_leads_by_the_outcome_of_their_latest_call(
    api: TestClient, migrated_url: str
) -> None:
    owner, _w = world(api, migrated_url)
    board = api.get("/leads/board", headers=owner).json()
    assert board["counts"] == {"interested": 1, "not_interested": 1, "no_outcome": 1}
    assert [c["phone"] for c in board["columns"]["interested"]] == ["+919876543210"]
    assert [c["phone"] for c in board["columns"]["no_outcome"]] == ["+919876543212"]


def test_lead_detail_has_calls_notes_and_memory_and_can_be_renamed(
    api: TestClient, migrated_url: str
) -> None:
    owner, w = world(api, migrated_url)
    lead = w["leads"]["a"]
    sql(migrated_url, "UPDATE leads SET memory = 'Prefers evenings.' WHERE id = :i", {"i": lead})
    api.post(f"/leads/{lead}/notes", json={"body": "VIP"}, headers=owner)
    body = api.get(f"/leads/{lead}", headers=owner).json()
    assert [c["summary"] for c in body["calls"]] == [
        "second",
        "first",
    ]  # newest first, no test calls
    assert [n["body"] for n in body["notes"]] == ["VIP"] and body["memory"] == "Prefers evenings."
    assert (
        api.patch(f"/leads/{lead}", json={"name": "  Ravi K  "}, headers=owner).json()["name"]
        == "Ravi K"
    )
    assert api.patch(f"/leads/{lead}", json={"name": " "}, headers=owner).json()["name"] is None


def test_export_has_only_the_columns_asked_for(api: TestClient, migrated_url: str) -> None:
    owner, _ = world(api, migrated_url)
    default = list(csv.reader(io.StringIO(api.get("/leads/export.csv", headers=owner).text)))
    assert default[0] == ["phone", "name", "last_outcome", "calls"] and len(default) == 4
    picked = api.get(
        "/leads/export.csv?fields=name,field:budget,last_outcome&q=Ravi", headers=owner
    )
    rows = list(csv.reader(io.StringIO(picked.text)))
    assert rows == [["name", "field:budget", "last_outcome"], ["Ravi", "5 lakh", "interested"]]
    assert "attachment" in picked.headers["content-disposition"]


def test_export_refuses_unknown_columns_and_cannot_be_used_for_formulas(
    api: TestClient, migrated_url: str
) -> None:
    owner, w = world(api, migrated_url)
    for bad in ("fields=password_hash", "fields=phone,id", "fields="):
        assert api.get(f"/leads/export.csv?{bad}", headers=owner).status_code == 422, bad
    add_lead(migrated_url, w["account"], "+919876543299", "=1+1", note="@SUM(A1)")
    csv_text = api.get("/leads/export.csv?fields=name,field:note&q=43299", headers=owner).text
    assert list(csv.reader(io.StringIO(csv_text)))[1] == ["'=1+1", "'@SUM(A1)"]


def test_leads_are_scoped_to_the_account(api: TestClient, migrated_url: str) -> None:
    _owner, w = world(api, migrated_url)
    other = signup(api, "b@example.com", "B")
    assert api.get("/leads", headers=other).json()["total"] == 0
    assert api.get("/leads/board", headers=other).json() == {"columns": {}, "counts": {}}
    lead = w["leads"]["a"]
    for method, path, body in (
        ("GET", "", None),
        ("PATCH", "", {"name": "x"}),
        ("GET", "/notes", None),
        ("POST", "/notes", {"body": "x"}),
        ("DELETE", "/memory", None),
    ):
        assert (
            api.request(method, f"/leads/{lead}{path}", headers=other, json=body).status_code == 404
        ), path
