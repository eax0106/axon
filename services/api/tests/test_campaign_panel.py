"""The live panel of a campaign: what it shows and every action the owner can take from it."""

import csv
import io
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from app.providers.telephony.vobiz import VobizTelephony

from .campaigning import (
    NOW,
    Carrier,
    contact_rows,
    end_call,
    make_campaign,
    open_calls,
    setup_bulk,
    states,
    tick,
)
from .conftest import sql

A, B, C, D = "+919876543210", "+919876543211", "+919876543212", "+919876543213"
LOCAL = ["9876543210", "9876543211", "9876543212", "9876543213"]


def contact_id(url: str, phone: str) -> str:
    return str(sql(url, "SELECT id FROM campaign_contacts WHERE phone = :p", {"p": phone}))


def live(api: TestClient, owner: dict[str, str], campaign: str) -> dict[str, Any]:
    found: dict[str, Any] = api.get(f"/campaigns/{campaign}/live", headers=owner).json()
    return found


def test_the_panel_shows_who_is_being_called_who_is_waiting_and_what_is_done(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, LOCAL, concurrency=2)
    tick(migrated_url, adapter, NOW)
    panel = live(api, owner, campaign)
    assert panel["status"] == "running" and panel["remaining"] == 2 and panel["done"] == 0
    assert [c["phone"] for c in panel["calling_now"]] == [A, B]
    assert all(c["call_id"] and c["attempt"] == 1 for c in panel["calling_now"])
    first = open_calls(migrated_url)[0]
    end_call(migrated_url, fake, adapter, first, NOW + timedelta(seconds=40), answered=True)
    panel = live(api, owner, campaign)
    assert panel["done"] == 1 and [c["phone"] for c in panel["calling_now"]] == [B]
    assert panel["counts"]["pending"] == 2 and panel["counts"]["done"] == 1


def test_the_panel_lists_callbacks_in_the_order_they_are_due(
    api: TestClient, migrated_url: str
) -> None:
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, LOCAL[:2])
    later, sooner = NOW + timedelta(days=1), NOW + timedelta(hours=3)
    for phone, when in ((A, later), (B, sooner)):
        sql(
            migrated_url,
            "UPDATE campaign_contacts SET status = 'callback', next_attempt_at = :t"
            " WHERE phone = :p",
            {"t": when, "p": phone},
        )
    callbacks = live(api, owner, campaign)["callbacks"]
    assert [(c["phone"], datetime.fromisoformat(c["at"])) for c in callbacks] == [
        (B, sooner),
        (A, later),
    ]


def test_retry_exhausted_gives_gave_up_contacts_a_fresh_ladder_and_reopens_a_finished_campaign(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, LOCAL[:1], retries=0)
    tick(migrated_url, adapter, NOW)
    end_call(migrated_url, fake, adapter, open_calls(migrated_url)[0], NOW + timedelta(seconds=30))
    tick(migrated_url, adapter, NOW + timedelta(seconds=40))
    assert states(migrated_url) == {A: "exhausted"}
    assert api.get(f"/campaigns/{campaign}", headers=owner).json()["status"] == "completed"
    moved = api.post(f"/campaigns/{campaign}/retry-exhausted", headers=owner).json()
    assert moved == {"moved": 1, "status": "paused"}  # nobody is called until the owner resumes
    assert contact_rows(migrated_url)[0][1:3] == ("pending", 0)
    assert tick(migrated_url, adapter, NOW + timedelta(minutes=5)) == []
    api.post(f"/campaigns/{campaign}/resume", headers=owner)
    assert len(tick(migrated_url, adapter, NOW + timedelta(minutes=6))) == 1
    assert api.post(f"/campaigns/{campaign}/retry-exhausted", headers=owner).json()["moved"] == 0


def test_cancel_callbacks_cancels_only_the_waiting_callbacks(
    api: TestClient, migrated_url: str
) -> None:
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, LOCAL[:3])
    sql(
        migrated_url,
        "UPDATE campaign_contacts SET status = 'callback', next_attempt_at = now()"
        " WHERE phone = :p",
        {"p": A},
    )
    moved = api.post(f"/campaigns/{campaign}/cancel-callbacks", headers=owner).json()
    assert moved == {"moved": 1}
    assert states(migrated_url) == {A: "canceled", B: "pending", C: "pending"}
    assert contact_rows(migrated_url)[0][4] == "callback cancelled"


def test_restore_not_called_brings_back_only_contacts_nobody_called(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, LOCAL, concurrency=1)
    api.post(f"/campaigns/{campaign}/exclusions", json={"text": "9876543213"}, headers=owner)
    tick(migrated_url, adapter, NOW)  # A is being called
    end_call(
        migrated_url,
        fake,
        adapter,
        open_calls(migrated_url)[0],
        NOW + timedelta(seconds=30),
        answered=True,
    )
    api.post(f"/campaigns/{campaign}/cancel", headers=owner)
    assert states(migrated_url) == {A: "done", B: "canceled", C: "canceled", D: "skipped"}
    sql(migrated_url, "UPDATE campaign_contacts SET attempts = 1 WHERE phone = :p", {"p": C})
    restored = api.post(f"/campaigns/{campaign}/restore-not-called", headers=owner).json()
    assert restored == {"moved": 1, "status": "paused"}
    assert states(migrated_url) == {A: "done", B: "pending", C: "canceled", D: "skipped"}


def test_call_now_puts_a_contact_first_and_still_respects_the_hours(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, LOCAL, concurrency=1)
    target = contact_id(migrated_url, D)
    answer = api.post(f"/campaigns/{campaign}/contacts/{target}/call-now", headers=owner)
    assert answer.status_code == 200 and "dials_at" in answer.json()
    placed = tick(migrated_url, adapter, NOW)
    assert len(placed) == 1
    assert states(migrated_url) == {A: "pending", B: "pending", C: "pending", D: "calling"}
    assert fake.placed[0]["to"] == "919876543213"
    # Out of hours the promise is the next opening, and nothing is dialed.
    night = datetime(2026, 11, 2, 16, 30, tzinfo=UTC)
    other = contact_id(migrated_url, B)
    shut = api.post(f"/campaigns/{campaign}/contacts/{other}/call-now", headers=owner)
    assert shut.status_code == 200
    assert tick(migrated_url, adapter, night) == []


def test_call_now_gives_a_gave_up_contact_another_try_and_refuses_a_paused_campaign(
    api: TestClient, migrated_url: str
) -> None:
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, LOCAL[:2])
    gave_up = contact_id(migrated_url, A)
    sql(
        migrated_url,
        "UPDATE campaign_contacts SET status = 'exhausted', attempts = 3 WHERE id = :i",
        {"i": gave_up},
    )
    assert (
        api.post(f"/campaigns/{campaign}/contacts/{gave_up}/call-now", headers=owner).status_code
        == 200
    )
    assert contact_rows(migrated_url)[0][1:3] == ("pending", 0)
    api.post(f"/campaigns/{campaign}/pause", headers=owner)
    paused = api.post(f"/campaigns/{campaign}/contacts/{gave_up}/call-now", headers=owner)
    assert paused.status_code == 409 and "resume" in paused.json()["detail"]
    api.post(f"/campaigns/{campaign}/resume", headers=owner)
    skipped = contact_id(migrated_url, B)
    sql(
        migrated_url,
        "UPDATE campaign_contacts SET status = 'skipped' WHERE id = :i",
        {"i": skipped},
    )
    assert (
        api.post(f"/campaigns/{campaign}/contacts/{skipped}/call-now", headers=owner).status_code
        == 409
    )


def test_one_contact_can_be_cancelled_and_retried(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    _, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, LOCAL[:3], concurrency=1)
    calling = contact_id(migrated_url, A)
    waiting = contact_id(migrated_url, B)
    tick(migrated_url, adapter, NOW)
    refused = api.post(f"/campaigns/{campaign}/contacts/{calling}/cancel", headers=owner)
    assert refused.status_code == 409  # a call is under way
    cancelled = api.post(f"/campaigns/{campaign}/contacts/{waiting}/cancel", headers=owner)
    assert cancelled.json() == {"status": "canceled"}
    assert contact_rows(migrated_url)[1][4] == "cancelled by a person"
    assert (
        api.post(f"/campaigns/{campaign}/contacts/{waiting}/cancel", headers=owner).status_code
        == 409
    )
    back = api.post(f"/campaigns/{campaign}/contacts/{waiting}/retry", headers=owner).json()
    assert back["status"] == "pending" and back["campaign_status"] == "running"
    done = contact_id(migrated_url, C)
    assert (
        api.post(f"/campaigns/{campaign}/contacts/{done}/retry", headers=owner).status_code == 409
    )  # pending
    ghost = "00000000-0000-0000-0000-000000000000"
    assert (
        api.post(f"/campaigns/{campaign}/contacts/{ghost}/cancel", headers=owner).status_code == 404
    )


def test_an_answered_contact_can_be_retried_and_reopens_a_completed_campaign(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, LOCAL[:1])
    tick(migrated_url, adapter, NOW)
    end_call(
        migrated_url,
        fake,
        adapter,
        open_calls(migrated_url)[0],
        NOW + timedelta(seconds=30),
        answered=True,
    )
    tick(migrated_url, adapter, NOW + timedelta(seconds=40))
    assert api.get(f"/campaigns/{campaign}", headers=owner).json()["status"] == "completed"
    target = contact_id(migrated_url, A)
    back = api.post(f"/campaigns/{campaign}/contacts/{target}/retry", headers=owner).json()
    assert back == {"status": "pending", "campaign_status": "paused"}


def test_the_contact_export_is_a_csv_a_spreadsheet_cannot_run(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url, variables=("city",))
    campaign = make_campaign(api, owner, employee, None, start=False, consent=False)
    api.post(
        f"/campaigns/{campaign}/contacts",
        json=[
            {
                "phone": "9876543210",
                "name": '=HYPERLINK("http://evil")',
                "variables": {"city": "Pune"},
            },
            {"phone": "9876543211", "name": "Asha"},
        ],
        headers=owner,
    )
    api.post(f"/campaigns/{campaign}/consent", json={"confirm": True}, headers=owner)
    api.post(f"/campaigns/{campaign}/start", headers=owner)
    tick(migrated_url, adapter, NOW)
    end_call(
        migrated_url,
        fake,
        adapter,
        open_calls(migrated_url)[0],
        NOW + timedelta(seconds=30),
        answered=True,
    )
    response = api.get(f"/campaigns/{campaign}/export.csv", headers=owner)
    assert response.headers["content-type"].startswith("text/csv")
    assert f"campaign-{campaign}.csv" in response.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert [r["phone"] for r in rows] == [f"'{A}", f"'{B}"]  # a leading + is a formula to a sheet
    assert rows[0]["name"] == '\'=HYPERLINK("http://evil")'  # a leading ' keeps it text
    assert (rows[0]["status"], rows[0]["attempts"], rows[0]["city"]) == ("done", "1", "Pune")
    assert (rows[0]["last_call_status"], rows[0]["last_call_seconds"]) == ("completed", "35")
    assert rows[1]["status"] == "calling" and rows[1]["city"] == ""
