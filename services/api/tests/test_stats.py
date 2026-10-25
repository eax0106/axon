"""Dashboard numbers against a seeded week with known answers (worked out by hand in comments)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from .conftest import sql
from .helpers import add_call, add_lead, live_employee, seed, signup

RANGE = "range=custom&date_from=2026-10-01T00:00:00Z&date_to=2026-10-08T00:00:00Z"


def ist(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC) - timedelta(minutes=330)


@pytest.fixture
def api(db_client: TestClient, migrated_url: str) -> TestClient:
    seed(migrated_url)
    return db_client


def seeded(api: TestClient, url: str) -> dict[str, Any]:
    owner = signup(api)
    asha = live_employee(api, url, owner)  # Instant
    ravi = live_employee(api, url, owner, channel="bulk", number="+911400000002")
    account = sql(url, "SELECT account_id FROM employees LIMIT 1")
    lead = add_lead(url, account, "+919876543210", "Ravi")

    def call(
        employee: Any, when: datetime, status: str, outcome: str | None = None, **kw: Any
    ) -> Any:
        return add_call(
            url, account, employee, lead, status=status, outcome=outcome, created_at=when, **kw
        )

    # Asha, hour 10 IST: 5 placed, 3 connected (interested, callback, not interested).
    a = [
        call(asha, ist(2, 10, 0), "completed", "interested"),
        call(asha, ist(2, 10, 30), "completed", "callback_requested"),
        call(asha, ist(3, 10, 45), "completed", "not_interested"),
        call(asha, ist(3, 10, 50), "no_answer"),
        call(asha, ist(4, 10, 55), "busy"),
        call(asha, ist(4, 11, 0), "failed"),  # hour 11: 1 placed
    ]
    # Ravi (bulk), hour 15 IST: 5 placed, 2 connected, both interested.
    for minute, status in (
        (0, "completed"),
        (5, "completed"),
        (10, "no_answer"),
        (15, "no_answer"),
        (20, "no_answer"),
    ):
        call(
            ravi,
            ist(5, 15, minute),
            status,
            "interested" if status == "completed" else None,
            channel="bulk",
        )
    # One answered inbound call, no employee. It counts as connected but is not "placed".
    call(None, ist(6, 12, 0), "completed", "other", direction="inbound", channel="inbound")
    # Never counted: a test call, calls still waiting or ringing, and one outside the range.
    call(asha, ist(2, 10, 5), "completed", "interested", is_test=True)
    call(asha, ist(2, 10, 6), "queued")
    call(asha, ist(2, 10, 7), "ringing")
    call(asha, ist(20, 10, 0), "completed", "interested")
    # Instant speed: four accepted leads, three of them called; two within a minute (10 s, 59 s).
    for index, (delay, source) in enumerate(((10, "website"), (59, "website"), (61, "meta"))):
        sql(
            url,
            "UPDATE calls SET started_at = :s WHERE id = :c",
            {"s": ist(2, 9, 0) + timedelta(seconds=delay), "c": a[index]},
        )
        sql(
            url,
            "INSERT INTO lead_intake_log (account_id, employee_id, source, status, phone, call_id,"
            " created_at) VALUES (:a, :e, :src, 'accepted', '+919876543210', :c, :t)",
            {"a": account, "e": asha, "src": source, "c": a[index], "t": ist(2, 9, 0)},
        )
    for source, status, call_id in (
        ("website", "accepted", None),
        ("test", "accepted", a[0]),
        ("website", "deduplicated", None),
    ):
        sql(
            url,
            "INSERT INTO lead_intake_log (account_id, employee_id, source, status, phone, call_id,"
            " created_at) VALUES (:a, :e, :src, :st, '+919876543210', :c, :t)",
            {"a": account, "e": asha, "src": source, "st": status, "c": call_id, "t": ist(2, 9, 0)},
        )
    return {"owner": owner, "asha": str(asha), "ravi": str(ravi)}


def test_totals_and_rates_match_the_hand_count(api: TestClient, migrated_url: str) -> None:
    w = seeded(api, migrated_url)
    body = api.get(f"/stats/overview?{RANGE}", headers=w["owner"]).json()
    # 6 Asha + 5 Ravi + 1 inbound; placed = the 11 outbound; connected = 3 + 2 + 1 inbound.
    assert body["totals"] == {
        "calls": 12,
        "placed": 11,
        "connected": 6,
        "qualified": 4,
        "converted": 3,
    }
    assert body["rates"] == {
        "connect": round(5 / 11, 4),
        "qualify": round(4 / 6, 4),
        "conversion": 0.5,
    }
    assert body["range"] == "custom"


def test_channel_split_counts_every_final_call_by_channel(
    api: TestClient, migrated_url: str
) -> None:
    w = seeded(api, migrated_url)
    assert api.get(f"/stats/overview?{RANGE}", headers=w["owner"]).json()["channel_split"] == {
        "instant": 6, "bulk": 5, "inbound": 1,
    }  # fmt: skip


def test_best_hour_is_the_best_connect_rate_among_hours_with_enough_calls(
    api: TestClient, migrated_url: str
) -> None:
    w = seeded(api, migrated_url)
    body = api.get(f"/stats/overview?{RANGE}", headers=w["owner"]).json()
    hours = {h["hour"]: h for h in body["by_hour"]}
    assert (hours[10]["placed"], hours[10]["connected"], hours[10]["connect_rate"]) == (5, 3, 0.6)
    assert (hours[15]["placed"], hours[15]["connected"], hours[15]["connect_rate"]) == (5, 2, 0.4)
    assert (hours[11]["placed"], hours[11]["connect_rate"]) == (
        1,
        0.0,
    )  # too few calls to be "best"
    assert 12 not in hours  # the inbound call is not an outbound attempt
    assert body["best_hour"] == 10


def test_the_leaderboard_ranks_by_conversions_then_connections(
    api: TestClient, migrated_url: str
) -> None:
    w = seeded(api, migrated_url)
    board = api.get(f"/stats/overview?{RANGE}", headers=w["owner"]).json()["leaderboard"]
    assert [r["employee_id"] for r in board] == [w["ravi"], w["asha"]]
    ravi, asha = board
    assert (ravi["placed"], ravi["connected"], ravi["qualified"], ravi["converted"]) == (5, 2, 2, 2)
    assert (asha["placed"], asha["connected"], asha["qualified"], asha["converted"]) == (6, 3, 2, 1)


def test_speed_counts_instant_leads_first_called_within_a_minute(
    api: TestClient, migrated_url: str
) -> None:
    w = seeded(api, migrated_url)
    speed = api.get(f"/stats/overview?{RANGE}", headers=w["owner"]).json()["speed"]
    # Accepted real leads: 4 (the test-source and deduplicated entries are not leads). Called within
    # 60 s: the 10 s and 59 s ones. The 61 s one and the one never called do not count.
    assert speed == {"accepted": 4, "within_60s": 2, "rate": 0.5}


def test_an_account_with_no_calls_has_nulls_not_zero_divisions(api: TestClient) -> None:
    owner = signup(api)
    body = api.get(f"/stats/overview?{RANGE}", headers=owner).json()
    assert body["totals"] == {
        "calls": 0,
        "placed": 0,
        "connected": 0,
        "qualified": 0,
        "converted": 0,
    }
    assert body["rates"] == {"connect": None, "qualify": None, "conversion": None}
    assert body["best_hour"] is None and body["leaderboard"] == [] and body["speed"]["rate"] is None


def test_ranges_7_30_and_90_days_and_custom_validation(api: TestClient, migrated_url: str) -> None:
    owner = signup(api)
    employee = live_employee(api, migrated_url, owner)
    account = sql(migrated_url, "SELECT account_id FROM employees")
    now = datetime.now(UTC)
    for days_ago in (1, 20, 60, 120):
        add_call(migrated_url, account, employee, None, created_at=now - timedelta(days=days_ago))
    totals = {
        r: api.get(f"/stats/overview?range={r}", headers=owner).json()["totals"]["calls"]
        for r in ("7d", "30d", "90d")
    }
    assert totals == {"7d": 1, "30d": 2, "90d": 3}
    window = f"date_from={(now - timedelta(days=30)).isoformat()}&date_to={now.isoformat()}"
    assert (
        api.get(
            f"/stats/overview?range=custom&{window}".replace("+", "%2B"), headers=owner
        ).status_code
        == 200
    )
    bad_ranges = (
        "range=custom",
        "range=custom&date_from=2026-10-08T00:00:00Z&date_to=2026-10-01T00:00:00Z",
        "range=1y",
    )
    for bad in bad_ranges:
        assert api.get(f"/stats/overview?{bad}", headers=owner).status_code == 422, bad


def test_stats_are_scoped_to_the_account(api: TestClient, migrated_url: str) -> None:
    w = seeded(api, migrated_url)
    other = signup(api, "b@example.com", "B")
    assert api.get(f"/stats/overview?{RANGE}", headers=other).json()["totals"]["calls"] == 0
    assert api.get(f"/stats/overview?{RANGE}").status_code == 401
    assert w
