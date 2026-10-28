"""lead.created and campaign.status_changed, from the real paths that cause them."""

from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.campaigns import runner
from app.providers.telephony.vobiz import VobizTelephony

from . import dialing
from .campaigning import NOW as CAMPAIGN_NOW
from .campaigning import PHONES, Carrier, make_campaign, setup_bulk, tick
from .conftest import sql
from .developer_support import events_of
from .helpers import account_id, add_lead, live_employee, run_db, signup


def test_a_lead_from_intake_is_announced_once_and_an_existing_lead_is_not(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    employee = live_employee(api, migrated_url, owner, variables=("budget",))
    dialing.lead_in(migrated_url, employee, "98765 00001", name="Asha", budget="80 lakh")
    (event,) = events_of(migrated_url, "lead.created")
    lead = event["data"]["lead"]
    assert lead["phone"] == "+919876500001" and lead["name"] == "Asha"
    assert lead["variables"] == {"budget": "80 lakh"} and lead["id"] and lead["created_at"]
    assert event["employee_id"] is None
    stored = sql(migrated_url, "SELECT id::text FROM leads WHERE phone = '+919876500001'")
    assert stored == lead["id"]  # the id announced is the id stored

    dialing.lead_in(migrated_url, employee, "+919876500001", name="Asha K")  # same person again
    assert len(events_of(migrated_url, "lead.created")) == 1
    dialing.lead_in(migrated_url, employee, "+919876500002")
    assert len(events_of(migrated_url, "lead.created")) == 2


def test_a_lead_a_campaign_makes_is_announced_and_one_it_already_had_is_not(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    _, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    known, fresh = PHONES[:2]
    add_lead(migrated_url, account_id(api, owner), f"+91{known}", "Asha")  # from before B12 hooks
    make_campaign(api, owner, employee, [known, fresh], concurrency=2)
    assert len(tick(migrated_url, adapter, CAMPAIGN_NOW)) == 2

    (event,) = events_of(migrated_url, "lead.created")
    lead = event["data"]["lead"]
    assert lead["phone"] == f"+91{fresh}" and lead["id"] and lead["created_at"]
    stored = sql(migrated_url, "SELECT id::text FROM leads WHERE phone = :p", {"p": lead["phone"]})
    assert lead["id"] == stored

    tick(migrated_url, adapter, CAMPAIGN_NOW + timedelta(minutes=5))  # nothing new is announced
    assert len(events_of(migrated_url, "lead.created")) == 1


def test_a_rejected_lead_announces_nothing(api: TestClient, migrated_url: str) -> None:
    owner = signup(api)
    employee = live_employee(api, migrated_url, owner)
    dialing.lead_in(migrated_url, employee, "not a number")
    assert events_of(migrated_url) == []


def statuses(url: str) -> list[tuple[str, str]]:
    return [
        (e["data"]["previous_status"], e["data"]["campaign"]["status"])
        for e in events_of(url, "campaign.status_changed")
    ]


def test_every_change_of_a_campaigns_status_is_announced_with_the_old_and_the_new(
    api: TestClient, migrated_url: str
) -> None:
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, PHONES[:2], start=False)
    base = f"/campaigns/{campaign}"
    assert events_of(migrated_url, "campaign.status_changed") == []  # making one is not a change

    for step in ("start", "pause", "resume", "cancel"):
        response = api.post(f"{base}/{step}", headers=owner)
        assert response.status_code in (200, 202), (step, response.text)
    assert statuses(migrated_url) == [
        ("draft", "running"),
        ("running", "paused"),
        ("paused", "running"),
        ("running", "canceled"),
    ]
    first = events_of(migrated_url, "campaign.status_changed")[0]["data"]["campaign"]
    assert first["id"] == campaign and first["employee_id"] == employee and first["name"]


def test_the_workers_starting_pausing_and_completing_of_campaigns_are_announced_too(
    api: TestClient, carrier: Any, migrated_url: str
) -> None:
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, PHONES[:1], start=False)
    start_at = (CAMPAIGN_NOW + timedelta(hours=1)).isoformat()
    scheduled = api.post(f"/campaigns/{campaign}/start", json={"start_at": start_at}, headers=owner)
    assert scheduled.status_code in (200, 202)
    assert statuses(migrated_url) == [("draft", "scheduled")]

    async def activate(factory: Any) -> int:
        async with factory() as session:
            n = await runner.activate_due(session, CAMPAIGN_NOW + timedelta(hours=2))
            await session.commit()
            return n

    assert run_db(migrated_url, activate) == 1
    assert statuses(migrated_url)[-1] == ("scheduled", "running")

    async def finish(factory: Any) -> int:
        async with factory() as session:
            await session.execute(text("DELETE FROM campaign_contacts"))  # nothing left to call
            n = await runner.finish_done(session, CAMPAIGN_NOW + timedelta(hours=3))
            await session.commit()
            return n

    assert run_db(migrated_url, finish) == 1
    assert statuses(migrated_url)[-1] == ("running", "completed")


def test_an_unknown_caller_becomes_a_lead_that_is_announced_once(
    api: TestClient, carrier: Any, migrated_url: str
) -> None:
    from .inbound_support import CALLER, inbound_employee, ring

    inbound_employee(api, migrated_url)
    fake, _ = carrier
    ring(migrated_url, fake)
    ring(migrated_url, fake)  # the same person calls again
    (event,) = events_of(migrated_url, "lead.created")
    assert event["data"]["lead"]["phone"] == CALLER and event["data"]["lead"]["name"] is None
