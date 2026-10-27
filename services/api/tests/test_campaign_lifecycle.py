"""Creating, editing and running a campaign through the API, with its owner's consent."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from .campaigning import (
    contacts_by_status,
    make_campaign,
    setup_bulk,
    signup_second,
)
from .conftest import sql
from .helpers import add_member, live_employee


def get(api: TestClient, owner: dict[str, str], campaign: str) -> dict[str, object]:
    found: dict[str, object] = api.get(f"/campaigns/{campaign}", headers=owner).json()
    return found


def test_a_campaign_is_made_on_a_bulk_employee_with_default_settings(
    api: TestClient, migrated_url: str
) -> None:
    employee, owner = setup_bulk(api, migrated_url)
    made = api.post(
        "/campaigns", json={"employee_id": employee, "name": "Diwali offer"}, headers=owner
    )
    assert made.status_code == 201
    body = made.json()
    assert body["status"] == "draft" and body["consent_given"] is False
    assert body["settings"]["concurrency"] == 2 and body["settings"]["retries"] == 2
    assert body["contacts"] == {
        "pending": 0, "calling": 0, "callback": 0, "done": 0,
        "exhausted": 0, "skipped": 0, "canceled": 0,
    }  # fmt: skip


def test_only_a_bulk_employee_of_the_callers_own_account_can_run_a_campaign(
    api: TestClient, migrated_url: str
) -> None:
    employee, owner = setup_bulk(api, migrated_url)
    instant = live_employee(api, migrated_url, owner, number="+911400000009")
    wrong_channel = api.post(
        "/campaigns", json={"employee_id": instant, "name": "x"}, headers=owner
    )
    assert wrong_channel.status_code == 409 and "Bulk" in wrong_channel.json()["detail"]
    other = signup_second(api)
    stranger = api.post("/campaigns", json={"employee_id": employee, "name": "x"}, headers=other)
    assert stranger.status_code == 404


def test_campaigns_are_listed_and_read_only_inside_their_account(
    api: TestClient, migrated_url: str
) -> None:
    employee, owner = setup_bulk(api, migrated_url)
    first = make_campaign(api, owner, employee, ["9876543210"], start=False, consent=False)
    second = make_campaign(api, owner, employee, ["9876543211"], name="Second", consent=True)
    listed = api.get("/campaigns", headers=owner).json()
    assert [c["id"] for c in listed] == [second, first]  # newest first
    running = api.get("/campaigns", params={"state": "running"}, headers=owner).json()
    assert [c["id"] for c in running] == [second]
    mine = api.get("/campaigns", params={"employee_id": employee}, headers=owner).json()
    assert len(mine) == 2
    other = signup_second(api)
    assert api.get("/campaigns", headers=other).json() == []
    for path in ("", "/live", "/capacity", "/analytics", "/export.csv", "/contacts", "/exclusions"):
        assert api.get(f"/campaigns/{first}{path}", headers=other).status_code == 404, path
    for action in ("start", "pause", "resume", "cancel", "retry-exhausted", "cancel-callbacks"):
        assert api.post(f"/campaigns/{first}/{action}", headers=other).status_code == 404, action


def test_a_campaign_does_not_start_without_the_owners_consent(
    api: TestClient, migrated_url: str
) -> None:
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, ["9876543210"], start=False, consent=False)
    refused = api.post(f"/campaigns/{campaign}/start", headers=owner)
    assert refused.status_code == 409 and "consent" in refused.json()["detail"]
    given = api.post(f"/campaigns/{campaign}/consent", json={"confirm": True}, headers=owner)
    assert given.status_code == 201 and "agreed to receive calls" in given.json()["statement"]
    recorded = api.get(f"/campaigns/{campaign}/consent", headers=owner).json()
    assert len(recorded) == 1 and recorded[0]["statement"] == given.json()["statement"]
    assert sql(migrated_url, "SELECT scope::text FROM consent_attestations") == "campaign"
    assert sql(migrated_url, "SELECT user_id FROM consent_attestations") is not None
    assert get(api, owner, campaign)["consent_given"] is True
    assert api.post(f"/campaigns/{campaign}/start", headers=owner).status_code == 200


def test_consent_needs_the_owner_and_an_explicit_yes(api: TestClient, migrated_url: str) -> None:
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, ["9876543210"], start=False, consent=False)
    member = add_member(api, migrated_url, owner)
    assert (
        api.post(
            f"/campaigns/{campaign}/consent", json={"confirm": True}, headers=member
        ).status_code
        == 403
    )
    assert (
        api.post(
            f"/campaigns/{campaign}/consent", json={"confirm": False}, headers=owner
        ).status_code
        == 422
    )
    assert api.post(f"/campaigns/{campaign}/consent", json={}, headers=owner).status_code == 422
    assert sql(migrated_url, "SELECT count(*) FROM consent_attestations") == 0


def test_a_campaign_needs_contacts_and_a_live_employee_with_a_number_to_start(
    api: TestClient, migrated_url: str
) -> None:
    employee, owner = setup_bulk(api, migrated_url)
    empty = make_campaign(api, owner, employee, None, start=False)
    refused = api.post(f"/campaigns/{empty}/start", headers=owner)
    assert refused.status_code == 409 and "add contacts" in refused.json()["detail"]
    only_skipped = make_campaign(api, owner, employee, ["9876543210"], start=False)
    api.post(f"/campaigns/{only_skipped}/exclusions", json={"text": "9876543210"}, headers=owner)
    assert api.post(f"/campaigns/{only_skipped}/start", headers=owner).status_code == 409
    ready = make_campaign(api, owner, employee, ["9876543211"], start=False)
    api.post(f"/employees/{employee}/deactivate", headers=owner)
    not_live = api.post(f"/campaigns/{ready}/start", headers=owner)
    assert not_live.status_code == 409 and "live" in not_live.json()["detail"]


def test_a_rule_that_forbids_the_calls_refuses_the_start_with_its_reason(
    api: TestClient, migrated_url: str
) -> None:
    employee, owner = setup_bulk(api, migrated_url, number_type="regular")
    campaign = make_campaign(api, owner, employee, ["9876543210"], start=False)
    refused = api.post(f"/campaigns/{campaign}/start", headers=owner)
    assert refused.status_code == 409
    assert "promotional" in refused.json()["detail"] or "140" in refused.json()["detail"]


def test_start_now_runs_it_and_start_later_schedules_it(api: TestClient, migrated_url: str) -> None:
    employee, owner = setup_bulk(api, migrated_url)
    now = make_campaign(api, owner, employee, ["9876543210"])
    running = get(api, owner, now)
    assert running["status"] == "running" and running["started_at"] is not None
    later = make_campaign(api, owner, employee, ["9876543211"], name="Later", start=False)
    when = datetime.now(UTC) + timedelta(days=1)
    scheduled = api.post(
        f"/campaigns/{later}/start", json={"start_at": when.isoformat()}, headers=owner
    ).json()
    assert scheduled["status"] == "scheduled" and scheduled["started_at"] is None
    assert datetime.fromisoformat(scheduled["scheduled_at"]) == when
    past = make_campaign(api, owner, employee, ["9876543212"], name="Past", start=False)
    stale = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    started = api.post(f"/campaigns/{past}/start", json={"start_at": stale}, headers=owner).json()
    assert started["status"] == "running"  # a time already gone means now


def test_pause_resume_and_cancel_move_the_campaign_and_refuse_wrong_moves(
    api: TestClient, migrated_url: str
) -> None:
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, ["9876543210", "9876543211"])
    assert api.post(f"/campaigns/{campaign}/resume", headers=owner).status_code == 409
    paused = api.post(f"/campaigns/{campaign}/pause", headers=owner).json()
    assert paused["status"] == "paused" and paused["note"] == "paused"
    assert api.post(f"/campaigns/{campaign}/pause", headers=owner).status_code == 409
    resumed = api.post(f"/campaigns/{campaign}/resume", headers=owner).json()
    assert resumed["status"] == "running" and resumed["note"] is None
    cancelled = api.post(f"/campaigns/{campaign}/cancel", headers=owner).json()
    assert cancelled["status"] == "canceled" and cancelled["contacts"]["canceled"] == 2
    for action in ("start", "pause", "resume", "cancel"):
        assert api.post(f"/campaigns/{campaign}/{action}", headers=owner).status_code == 409
    assert contacts_by_status(migrated_url) == {"canceled": 2}


def test_a_campaign_is_edited_only_while_it_is_not_calling(
    api: TestClient, migrated_url: str
) -> None:
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, ["9876543210"], start=False)
    changed = api.patch(
        f"/campaigns/{campaign}",
        json={"name": "Renamed", "purpose": "transactional", "settings": {"concurrency": 7}},
        headers=owner,
    ).json()
    assert changed["name"] == "Renamed" and changed["purpose"] == "transactional"
    assert changed["settings"]["concurrency"] == 7
    cleared = api.patch(f"/campaigns/{campaign}", json={"purpose": None}, headers=owner).json()
    assert cleared["purpose"] is None  # back to the employee's own purpose
    api.post(f"/campaigns/{campaign}/consent", json={"confirm": True}, headers=owner)
    api.post(f"/campaigns/{campaign}/start", headers=owner)
    assert api.patch(f"/campaigns/{campaign}", json={"name": "x"}, headers=owner).status_code == 409
    api.post(f"/campaigns/{campaign}/pause", headers=owner)
    assert (
        api.patch(f"/campaigns/{campaign}", json={"name": "Later"}, headers=owner).status_code
        == 200
    )


def test_settings_outside_the_limits_are_refused_with_a_422(
    api: TestClient, migrated_url: str
) -> None:
    employee, owner = setup_bulk(api, migrated_url)
    for bad in (
        {"concurrency": 21},
        {"retries": 10},
        {"window_start_min": 8 * 60},
        {"window_end_min": 22 * 60},
        {"holidays": ["not a date"]},
    ):
        made = api.post(
            "/campaigns",
            json={"employee_id": employee, "name": "x", "settings": bad},
            headers=owner,
        )
        assert made.status_code == 422, bad
    assert api.get("/campaigns", headers=owner).json() == []
