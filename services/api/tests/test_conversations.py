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
    """An account with two employees and a spread of calls with known answers."""
    owner = signup(api)
    asha = live_employee(api, url, owner)
    ravi = live_employee(api, url, owner, channel="bulk", number="+911400000002")
    account = sql(url, "SELECT account_id FROM employees LIMIT 1")
    lead_a = add_lead(url, account, "+919876543210", "Ravi")
    lead_b = add_lead(url, account, "+919876543211", "Sita")
    calls = {
        "interested": add_call(
            url,
            account,
            asha,
            lead_a,
            outcome="interested",
            sentiment="positive",
            duration_s=120,
            credits_charged=6,
            created_at=T0,
            summary="Wants a quote",
        ),
        "not_interested": add_call(
            url,
            account,
            asha,
            lead_b,
            outcome="not_interested",
            sentiment="negative",
            duration_s=20,
            credits_charged=1,
            created_at=T0 + timedelta(days=1),
        ),
        "bulk": add_call(
            url,
            account,
            ravi,
            lead_a,
            channel="bulk",
            outcome="callback_requested",
            sentiment="neutral",
            duration_s=60,
            credits_charged=3,
            created_at=T0 + timedelta(days=2),
        ),
        "inbound": add_call(
            url,
            account,
            ravi,
            lead_b,
            direction="inbound",
            channel="inbound",
            status="no_answer",
            created_at=T0 + timedelta(days=3),
        ),
        "test": add_call(
            url, account, asha, lead_a, is_test=True, created_at=T0 + timedelta(days=4)
        ),
    }
    return owner, {
        "asha": asha,
        "ravi": ravi,
        "calls": {k: str(v) for k, v in calls.items()},
        "account": account,
    }


def ids(response: Any) -> list[str]:
    return [item["id"] for item in response.json()["items"]]


def test_the_list_is_newest_first_without_test_calls_and_carries_the_row_fields(
    api: TestClient, migrated_url: str
) -> None:
    owner, w = world(api, migrated_url)
    body = api.get("/calls", headers=owner).json()
    c = w["calls"]
    assert body["total"] == 4 and ids(api.get("/calls", headers=owner)) == [
        c["inbound"],
        c["bulk"],
        c["not_interested"],
        c["interested"],
    ]
    first = body["items"][-1]
    assert (first["employee_name"], first["phone"], first["name"], first["outcome"]) == (
        "Asha",
        "+919876543210",
        "Ravi",
        "interested",
    )
    assert (first["duration_s"], first["credits_charged"], first["summary"]) == (
        120,
        6.0,
        "Wants a quote",
    )
    assert api.get("/calls?include_test=true", headers=owner).json()["total"] == 5


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("outcome=interested", ["interested"]),
        ("sentiment=negative", ["not_interested"]),
        ("channel=bulk", ["bulk"]),
        ("direction=inbound", ["inbound"]),
        ("min_duration=60", ["bulk", "interested"]),
        ("max_duration=60", ["bulk", "not_interested"]),
        ("min_credits=3&max_credits=6", ["bulk", "interested"]),
        ("date_from=2026-10-02T00:00:00Z&date_to=2026-10-04T00:00:00Z", ["bulk", "not_interested"]),
        ("q=Sita", ["inbound", "not_interested"]),
        ("q=43210", ["bulk", "interested"]),
        ("outcome=interested&channel=bulk", []),
    ],
)
def test_each_filter(api: TestClient, migrated_url: str, query: str, expected: list[str]) -> None:
    owner, w = world(api, migrated_url)
    got = ids(api.get(f"/calls?{query}", headers=owner))
    assert sorted(got) == sorted(w["calls"][k] for k in expected)


def test_filter_by_employee_and_campaign(api: TestClient, migrated_url: str) -> None:
    owner, w = world(api, migrated_url)
    only_ravi = ids(api.get(f"/calls?employee_id={w['ravi']}", headers=owner))
    assert sorted(only_ravi) == sorted([w["calls"]["bulk"], w["calls"]["inbound"]])
    campaign = sql(
        migrated_url,
        "INSERT INTO campaigns (account_id, employee_id, name, status)"
        " VALUES (:a, :e, 'C', 'draft') RETURNING id",
        {"a": w["account"], "e": w["ravi"]},
    )
    sql(
        migrated_url,
        "UPDATE calls SET campaign_id = :c WHERE id = :i",
        {"c": campaign, "i": w["calls"]["bulk"]},
    )
    assert ids(api.get(f"/calls?campaign_id={campaign}", headers=owner)) == [w["calls"]["bulk"]]


def test_pagination(api: TestClient, migrated_url: str) -> None:
    owner, _w = world(api, migrated_url)
    first = api.get("/calls?limit=3", headers=owner).json()
    rest = api.get("/calls?limit=3&offset=3", headers=owner).json()
    assert (
        first["total"] == rest["total"] == 4
        and len(first["items"]) == 3
        and len(rest["items"]) == 1
    )
    assert {i["id"] for i in first["items"]}.isdisjoint(i["id"] for i in rest["items"])
    for bad in ("limit=0", "limit=201", "offset=-1", "min_duration=-1", "date_from=nope"):
        assert api.get(f"/calls?{bad}", headers=owner).status_code == 422


def test_calls_are_scoped_to_the_account(api: TestClient, migrated_url: str) -> None:
    _owner, w = world(api, migrated_url)
    other = signup(api, "b@example.com", "B")
    assert api.get("/calls", headers=other).json() == {
        "total": 0,
        "limit": 50,
        "offset": 0,
        "items": [],
    }
    assert api.get("/calls/export.csv", headers=other).text.count("\n") == 1  # header only
    assert api.get("/calls", headers={}).status_code == 401
    assert api.get(f"/calls/{w['calls']['interested']}", headers=other).status_code == 404


def test_remembered_filters_round_trip_per_user_and_validate(
    api: TestClient, migrated_url: str
) -> None:
    owner, _w = world(api, migrated_url)
    assert api.get("/me/filters/conversations", headers=owner).json()["outcome"] is None
    mine = {
        "outcome": "interested",
        "channel": "instant",
        "min_duration": 30,
        "include_test": False,
    }
    saved = api.put("/me/filters/conversations", json=mine, headers=owner)
    assert saved.status_code == 200
    got = api.get("/me/filters/conversations", headers=owner).json()
    assert (got["outcome"], got["channel"], got["min_duration"]) == ("interested", "instant", 30)
    other = signup(api, "b@example.com", "B")
    assert api.get("/me/filters/conversations", headers=other).json()["outcome"] is None
    assert (
        api.put("/me/filters/conversations", json={"min_duration": -5}, headers=owner).status_code
        == 422
    )
    assert (
        api.put(
            "/me/filters/conversations", json={"employee_id": "nope"}, headers=owner
        ).status_code
        == 422
    )


def test_csv_export_follows_the_filters(api: TestClient, migrated_url: str) -> None:
    owner, _w = world(api, migrated_url)
    response = api.get("/calls/export.csv?channel=instant", headers=owner)
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0][:4] == ["time", "employee", "phone", "name"] and len(rows) == 3
    assert {r[7] for r in rows[1:]} == {"interested", "not_interested"}
    assert rows[1][5] == "instant" and rows[2][11] in ("Wants a quote", "")


def test_csv_cells_cannot_become_spreadsheet_formulas(api: TestClient, migrated_url: str) -> None:
    owner, w = world(api, migrated_url)
    evil = add_lead(
        migrated_url, w["account"], "+919876543299", '=HYPERLINK("http://evil","click")'
    )
    add_call(
        migrated_url, w["account"], w["asha"], evil, summary="+cmd|' /C calc'!A0", outcome="@sum"
    )
    rows = list(csv.reader(io.StringIO(api.get("/calls/export.csv?q=43299", headers=owner).text)))
    assert (
        rows[1][3].startswith("'=HYPERLINK")
        and rows[1][11].startswith("'+cmd")
        and rows[1][7] == "'@sum"
    )
    assert all(not cell.startswith(("=", "+", "@")) for row in rows for cell in row)


def test_csv_cells_with_leading_spaces_before_a_formula_are_neutralised_too() -> None:
    from app.calls.csvsafe import cell

    for risky in ("=1+1", "  =1+1", "\t+cmd", " @SUM(A1)", "\n-2"):
        assert cell(risky).startswith("'"), risky
    for fine in ("hello", "  hello", "a=b", "100", None):
        assert not cell(fine).startswith("'"), fine
    assert cell(None) == ""
