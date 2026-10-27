"""Campaign analytics, and the capacity preview that tells the owner how long it will take."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.providers.telephony.vobiz import VobizTelephony

from .campaigning import (
    NOW,
    Carrier,
    end_call,
    make_campaign,
    open_calls,
    setup_bulk,
    tick,
)
from .conftest import sql

LOCAL = ["9876543210", "9876543211", "9876543212"]


def test_analytics_count_attempts_answers_spend_outcomes_and_days(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, LOCAL, concurrency=3, retries=0)
    empty = api.get(f"/campaigns/{campaign}/analytics", headers=owner).json()
    assert (empty["attempts"], empty["answer_rate"], empty["by_day"]) == (0, 0, [])
    tick(migrated_url, adapter, NOW)
    first, second, third = open_calls(migrated_url)
    assert api.get(f"/campaigns/{campaign}/analytics", headers=owner).json()["attempts"] == 0
    end_call(migrated_url, fake, adapter, first, NOW + timedelta(seconds=40), answered=True)
    end_call(migrated_url, fake, adapter, second, NOW + timedelta(seconds=41))
    end_call(migrated_url, fake, adapter, third, NOW + timedelta(seconds=42))
    sql(
        migrated_url,
        "UPDATE calls SET outcome = 'interested', sentiment = 'positive', credits_charged = 1.5"
        " WHERE id = :c",
        {"c": first},
    )
    # A call started just after midnight in India belongs to the next day there.
    sql(
        migrated_url,
        "UPDATE calls SET started_at = :t WHERE id = :c",
        {"t": datetime(2026, 11, 2, 19, 0, tzinfo=UTC), "c": third},
    )
    stats = api.get(f"/campaigns/{campaign}/analytics", headers=owner).json()
    assert stats["attempts"] == 3 and stats["answered_calls"] == 1
    assert stats["answer_rate"] == 0.3333 and stats["avg_talk_seconds"] == 35.0
    assert stats["credits_spent"] == "1.5000"
    assert stats["outcomes"] == {"interested": 1} and stats["sentiment"] == {"positive": 1}
    assert stats["contacts"]["done"] == 1 and stats["contacts_reached"] == 1
    assert stats["by_day"] == [
        {"date": "2026-11-02", "attempts": 2, "answered": 1},
        {"date": "2026-11-03", "attempts": 1, "answered": 0},
    ]


def test_analytics_leave_out_test_calls_and_other_campaigns(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    _, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    mine = make_campaign(api, owner, employee, LOCAL[:1], name="Mine")
    make_campaign(api, owner, employee, LOCAL[1:2], name="Other", dedupe_days=0)
    tick(migrated_url, adapter, NOW)
    sql(migrated_url, "UPDATE calls SET is_test = true WHERE campaign_id = :c", {"c": mine})
    stats = api.get(f"/campaigns/{mine}/analytics", headers=owner).json()
    assert stats["attempts"] == 0


def test_the_capacity_preview_estimates_time_and_cost_from_the_numbers_lines(
    api: TestClient, migrated_url: str
) -> None:
    employee, owner = setup_bulk(api, migrated_url, channels=2)
    campaign = make_campaign(
        api, owner, employee, [f"98765432{i}0" for i in range(10)][:4], start=False, concurrency=5
    )
    preview = api.get(f"/campaigns/{campaign}/capacity", headers=owner).json()
    assert preview["remaining_contacts"] == 4
    assert (preview["number_channels"], preview["concurrency"], preview["parallel_calls"]) == (
        2,
        5,
        2,
    )
    assert preview["avg_talk_seconds"] == 90.0  # no answered calls yet: the default guess
    assert preview["calls_per_open_day"] == int(2 * 12 * 3600 / 105)
    assert preview["open_days_per_week"] == 7 and preview["working_days_needed"] == 1
    assert preview["estimated_cost"] == "21.0000"  # 4 contacts x 1.5 min x 3.5 credits
    assert preview["enough_credits"] is True and preview["queue_ahead"] == []


def test_the_capacity_preview_uses_the_employees_real_talk_time_and_the_balance(
    api: TestClient, migrated_url: str
) -> None:
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, LOCAL, start=False)
    account = sql(migrated_url, "SELECT account_id FROM employees")
    sql(
        migrated_url,
        "INSERT INTO calls (account_id, employee_id, direction, channel, status, duration_s)"
        " VALUES (:a, :e, 'outbound', 'bulk', 'completed', 60)",
        {"a": account, "e": employee},
    )
    sql(migrated_url, "UPDATE accounts SET credit_balance = 5")
    preview = api.get(f"/campaigns/{campaign}/capacity", headers=owner).json()
    assert preview["avg_talk_seconds"] == 60.0
    assert preview["estimated_cost"] == "10.5000"  # 3 contacts x 1 min x 3.5
    assert preview["credit_balance"] == "5.0000" and preview["enough_credits"] is False


def test_a_campaign_with_no_lines_has_no_estimate(api: TestClient, migrated_url: str) -> None:
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, LOCAL, start=False)
    sql(migrated_url, "UPDATE employees SET number_id = NULL")
    preview = api.get(f"/campaigns/{campaign}/capacity", headers=owner).json()
    assert preview["parallel_calls"] == 0 and preview["working_days_needed"] is None


def test_the_preview_names_the_older_campaigns_that_take_the_lines_first(
    api: TestClient, migrated_url: str
) -> None:
    employee, owner = setup_bulk(api, migrated_url)
    old = make_campaign(api, owner, employee, LOCAL[:1], name="Old")
    new = make_campaign(api, owner, employee, LOCAL[1:2], name="New")
    assert api.get(f"/campaigns/{old}/capacity", headers=owner).json()["queue_ahead"] == []
    assert api.get(f"/campaigns/{new}/capacity", headers=owner).json()["queue_ahead"] == ["Old"]
    api.post(f"/campaigns/{old}/pause", headers=owner)  # a paused campaign takes no line
    assert api.get(f"/campaigns/{new}/capacity", headers=owner).json()["queue_ahead"] == []
