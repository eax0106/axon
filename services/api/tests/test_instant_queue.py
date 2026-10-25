from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from .conftest import sql
from .helpers import live_employee, seed, signup


@pytest.fixture
def api(db_client: TestClient, migrated_url: str) -> TestClient:
    seed(migrated_url)
    return db_client


def setup(api: TestClient, url: str) -> tuple[str, dict[str, str], str]:
    owner = signup(api)
    employee = live_employee(api, url, owner)
    return employee, owner, f"/employees/{employee}/instant"


def lead_call(
    url: str, status: str, scheduled: str | None, attempt: int = 1, phone: str = "+919876543210"
) -> str:
    account = sql(url, "SELECT account_id FROM employees LIMIT 1")
    employee = sql(url, "SELECT id FROM employees LIMIT 1")
    lead = sql(url, "SELECT id FROM leads WHERE phone = :p", {"p": phone})
    if lead is None:
        lead = sql(
            url,
            "INSERT INTO leads (account_id, phone, name) VALUES (:a, :p, 'Ravi') RETURNING id",
            {"a": account, "p": phone},
        )
    return str(
        sql(
            url,
            "INSERT INTO calls (account_id, employee_id, lead_id, direction, channel, status,"
            " attempt, scheduled_for)"
            " VALUES (:a, :e, :l, 'outbound', 'instant', :s, :n, :sf) RETURNING id",
            {
                "a": account,
                "e": employee,
                "l": lead,
                "s": status,
                "n": attempt,
                "sf": datetime.now(UTC) if scheduled == "now" else None,
            },
        )
    )


def test_the_console_lists_waiting_held_and_ringing_calls_then_recent_ones(
    api: TestClient, migrated_url: str
) -> None:
    _, owner, base = setup(api, migrated_url)
    waiting = lead_call(migrated_url, "queued", "now", phone="+919876543210")
    held = lead_call(migrated_url, "queued", None, phone="+919876543211")
    ringing = lead_call(migrated_url, "ringing", None, phone="+919876543212")
    done = lead_call(migrated_url, "completed", None, attempt=2, phone="+919876543213")
    queue = api.get(base + "/queue", headers=owner).json()
    by_id = {i["call_id"]: i for i in queue["active"]}
    assert {i: by_id[i]["state"] for i in by_id} == {
        waiting: "waiting",
        held: "held",
        ringing: "ringing",
    }
    assert by_id[waiting]["phone"] == "+919876543210" and by_id[waiting]["name"] == "Ravi"
    assert [i["call_id"] for i in queue["recent"]] == [done] and queue["recent"][0]["attempt"] == 2
    assert api.get(base + "/queue?recent=0", headers=owner).json()["recent"] == []


def test_test_calls_are_not_in_the_console(api: TestClient, migrated_url: str) -> None:
    _, owner, base = setup(api, migrated_url)
    lead_call(migrated_url, "queued", "now")
    sql(migrated_url, "UPDATE calls SET is_test = true")
    queue = api.get(base + "/queue", headers=owner).json()
    assert queue == {"active": [], "recent": []}


def test_cancel_only_takes_a_waiting_or_held_call(api: TestClient, migrated_url: str) -> None:
    _, owner, base = setup(api, migrated_url)
    waiting = lead_call(migrated_url, "queued", "now")
    ringing = lead_call(migrated_url, "ringing", None, phone="+919876543211")
    assert api.post(f"{base}/queue/{waiting}/cancel", headers=owner).json()["status"] == "canceled"
    assert api.post(f"{base}/queue/{ringing}/cancel", headers=owner).status_code == 409
    assert (
        api.post(f"{base}/queue/{waiting}/cancel", headers=owner).status_code == 409
    )  # already cancelled


def test_redial_releases_a_held_call(api: TestClient, migrated_url: str) -> None:
    _, owner, base = setup(api, migrated_url)
    held = lead_call(migrated_url, "queued", None)
    response = api.post(f"{base}/queue/{held}/redial", headers=owner)
    assert response.status_code == 202 and response.json()["call_id"] == held
    assert (
        sql(migrated_url, "SELECT scheduled_for IS NOT NULL FROM calls WHERE id = :c", {"c": held})
        is True
    )


def test_redial_of_a_finished_call_starts_again_from_attempt_one(
    api: TestClient, migrated_url: str
) -> None:
    _, owner, base = setup(api, migrated_url)
    last = lead_call(migrated_url, "no_answer", None, attempt=10)
    again = api.post(f"{base}/queue/{last}/redial", headers=owner).json()["call_id"]
    assert again != last
    row = sql(
        migrated_url, "SELECT attempt::text || status::text FROM calls WHERE id = :c", {"c": again}
    )
    assert row == "1queued"
    assert sql(migrated_url, "SELECT count(*) FROM calls") == 2


def test_redial_is_refused_for_calls_under_way_dnc_numbers_and_paused_employees(
    api: TestClient, migrated_url: str
) -> None:
    employee, owner, base = setup(api, migrated_url)
    under_way = lead_call(migrated_url, "in_progress", None)
    assert api.post(f"{base}/queue/{under_way}/redial", headers=owner).status_code == 409
    finished = lead_call(migrated_url, "busy", None, phone="+919876543211")
    account = sql(migrated_url, "SELECT account_id FROM employees")
    sql(
        migrated_url,
        "INSERT INTO dnc_entries (account_id, phone, source)"
        " VALUES (:a, '+919876543211', 'manual')",
        {"a": account},
    )
    refused = api.post(f"{base}/queue/{finished}/redial", headers=owner)
    assert refused.status_code == 409 and "do-not-call" in refused.text
    other = lead_call(migrated_url, "busy", None, phone="+919876543212")
    api.post(f"/employees/{employee}/deactivate", headers=owner)
    assert api.post(f"{base}/queue/{other}/redial", headers=owner).status_code == 409


def test_a_one_off_call_runs_the_same_rules_but_skips_the_duplicate_check(
    api: TestClient, migrated_url: str
) -> None:
    _, owner, base = setup(api, migrated_url)
    body: dict[str, Any] = {"phone": "98765 43210", "name": "Walk-in"}
    first = api.post(base + "/call", json=body, headers=owner)
    again = api.post(base + "/call", json=body, headers=owner)
    assert first.status_code == 202 and again.status_code == 202
    assert (
        sql(migrated_url, "SELECT count(*) FROM calls") == 2
        and sql(migrated_url, "SELECT count(*) FROM leads") == 1
    )
    assert api.post(base + "/call", json={"phone": "12"}, headers=owner).status_code == 422
    account = sql(migrated_url, "SELECT account_id FROM employees")
    sql(
        migrated_url,
        "INSERT INTO dnc_entries (account_id, phone, source)"
        " VALUES (:a, '+919876543299', 'manual')",
        {"a": account},
    )
    blocked = api.post(base + "/call", json={"phone": "9876543299"}, headers=owner)
    assert blocked.status_code == 422 and "do-not-call" in blocked.text
    sources = sql(migrated_url, "SELECT string_agg(DISTINCT source, ',') FROM lead_intake_log")
    assert sources == "manual"


def test_the_console_is_scoped_to_the_account(api: TestClient, migrated_url: str) -> None:
    _, owner, base = setup(api, migrated_url)
    call = lead_call(migrated_url, "queued", "now")
    other = signup(api, "b@example.com", "B")
    for method, path in (
        ("GET", "/queue"),
        ("POST", f"/queue/{call}/cancel"),
        ("POST", f"/queue/{call}/redial"),
    ):
        assert api.request(method, base + path, headers=other).status_code == 404
    # And an employee in the same account cannot reach another employee's calls through its own id.
    second = live_employee(api, migrated_url, owner, number="+911400000002")
    assert (
        api.post(f"/employees/{second}/instant/queue/{call}/cancel", headers=owner).status_code
        == 404
    )


def test_a_double_click_on_redial_queues_the_lead_once(api: TestClient, migrated_url: str) -> None:
    _, owner, base = setup(api, migrated_url)
    last = lead_call(migrated_url, "no_answer", None, attempt=10)
    first = api.post(f"{base}/queue/{last}/redial", headers=owner).json()["call_id"]
    second = api.post(f"{base}/queue/{last}/redial", headers=owner).json()["call_id"]
    assert first == second
    assert sql(migrated_url, "SELECT count(*) FROM calls WHERE status = 'queued'") == 1
