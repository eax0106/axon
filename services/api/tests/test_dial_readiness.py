"""No call is started that the platform cannot carry: a leg with no healthy configured vendor, a
failing carrier, or the platform-wide limit on calls at once. Such calls wait; nothing is lost."""

from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.instant.dialer import CHANNEL_BUSY_RETRY, NOT_READY_RETRY
from app.providers import failover, health
from app.providers.telephony.vobiz import VobizTelephony

from .campaigning import make_campaign, setup_bulk
from .campaigning import tick as campaign_tick
from .conftest import sql
from .dialing import NOW, Carrier, lead_in, tick
from .helpers import add_call, live_employee, run_db, signup
from .inbound_support import inbound_employee, ring

PHONES = ["98765 43210", "98765 43211", "98765 43212", "98765 43213"]


def instant(api: TestClient, url: str, channels: int = 1) -> str:
    employee = live_employee(api, url, signup(api))
    sql(url, "UPDATE numbers SET channels = :c", {"c": channels})
    return employee


def failures(url: str, kind: str, vendor: str, count: int = 3) -> None:
    async def work(factory: Any) -> None:
        async with factory() as session:
            for _ in range(count):
                health.record(session, kind, vendor, ok=False, at=NOW - timedelta(minutes=1))
            await session.commit()

    run_db(url, work)


def platform_events(url: str) -> list[str]:
    reasons = sql(
        url,
        "SELECT string_agg(data->>'reason', '|' ORDER BY id) FROM call_events"
        " WHERE type = 'blocked_platform'",
    )
    return reasons.split("|") if reasons else []


def queued(url: str) -> str:
    return str(sql(url, "SELECT attempt || ':' || status FROM calls WHERE lead_id IS NOT NULL"))


def test_an_instant_call_waits_while_a_leg_has_no_configured_vendor(
    api: TestClient,
    migrated_url: str,
    carrier: tuple[Carrier, VobizTelephony],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake, adapter = carrier
    monkeypatch.delenv("SARVAM_API_KEY")
    lead_in(migrated_url, instant(api, migrated_url), PHONES[0], name="Ravi", now=NOW)
    due = NOW + timedelta(minutes=1)
    assert [d.outcome for d in tick(migrated_url, adapter, due)] == ["rescheduled"]
    assert fake.placed == []
    assert queued(migrated_url) == "1:queued"  # no attempt used up
    assert platform_events(migrated_url) == [
        "no speech-to-text provider is working right now; calls resume when one does"
    ]
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")
    assert [d.outcome for d in tick(migrated_url, adapter, due + NOT_READY_RETRY)] == ["dialed"]
    assert len(fake.placed) == 1


def test_an_instant_call_waits_while_every_vendor_of_a_leg_is_unhealthy(
    api: TestClient,
    migrated_url: str,
    carrier: tuple[Carrier, VobizTelephony],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake, adapter = carrier
    lead_in(migrated_url, instant(api, migrated_url), PHONES[0], name="Ravi", now=NOW)
    failures(migrated_url, "llm", "sarvam")  # Gemini has no key: Sarvam was the only LLM
    due = NOW + timedelta(minutes=1)
    assert [d.outcome for d in tick(migrated_url, adapter, due)] == ["rescheduled"]
    assert platform_events(migrated_url) == [
        "no AI model provider is working right now; calls resume when one does"
    ]
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")  # a healthy second LLM is enough
    assert [d.outcome for d in tick(migrated_url, adapter, due + NOT_READY_RETRY)] == ["dialed"]
    assert len(fake.placed) == 1


def test_an_unhealthy_vendor_is_healthy_again_once_its_failures_age_out(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    _, adapter = carrier
    lead_in(migrated_url, instant(api, migrated_url), PHONES[0], name="Ravi", now=NOW)
    failures(migrated_url, "tts", "sarvam")
    due = NOW + timedelta(minutes=1)
    assert [d.outcome for d in tick(migrated_url, adapter, due)] == ["rescheduled"]
    later = NOW + health.WINDOW + timedelta(minutes=1)
    assert [d.outcome for d in tick(migrated_url, adapter, later)] == ["dialed"]


def test_the_platform_limit_on_calls_at_once_holds_new_calls(
    api: TestClient,
    migrated_url: str,
    carrier: tuple[Carrier, VobizTelephony],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, adapter = carrier
    monkeypatch.setenv("AXON_MAX_CONCURRENT_CALLS", "1")
    employee = instant(api, migrated_url, channels=5)
    account = sql(migrated_url, "SELECT account_id FROM employees")
    other = add_call(migrated_url, account, status="in_progress")  # someone's call, up already
    lead_in(migrated_url, employee, PHONES[0], name="Ravi", now=NOW)
    due = NOW + timedelta(minutes=1)
    assert [d.outcome for d in tick(migrated_url, adapter, due)] == ["rescheduled"]
    assert platform_events(migrated_url) == [failover.CAPACITY]
    assert queued(migrated_url) == "1:queued"
    sql(migrated_url, "UPDATE calls SET status = 'completed' WHERE id = :c", {"c": other})
    soon = due + CHANNEL_BUSY_RETRY  # capacity frees up within seconds: it is looked at soon
    assert [d.outcome for d in tick(migrated_url, adapter, soon)] == ["dialed"]


def test_the_limit_counts_the_calls_placed_in_the_same_round(
    api: TestClient,
    migrated_url: str,
    carrier: tuple[Carrier, VobizTelephony],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake, adapter = carrier
    monkeypatch.setenv("AXON_MAX_CONCURRENT_CALLS", "2")
    employee = instant(api, migrated_url, channels=5)
    for phone in PHONES[:3]:
        lead_in(migrated_url, employee, phone, now=NOW)
    outcomes = sorted(d.outcome for d in tick(migrated_url, adapter, NOW + timedelta(minutes=1)))
    assert outcomes == ["dialed", "dialed", "rescheduled"] and len(fake.placed) == 2


@pytest.mark.parametrize("status", [503, 401, 429])
def test_carrier_failures_make_the_dialers_hold(
    api: TestClient,
    migrated_url: str,
    carrier: tuple[Carrier, VobizTelephony],
    status: int,
) -> None:
    fake, adapter = carrier
    employee = instant(api, migrated_url, channels=5)
    for phone in PHONES[:3]:
        lead_in(migrated_url, employee, phone, now=NOW)
    fake.refuse_with = status
    due = NOW + timedelta(minutes=1)
    assert [d.outcome for d in tick(migrated_url, adapter, due)] == ["failed"] * 3
    fake.refuse_with = 0
    lead_in(migrated_url, employee, PHONES[3], now=due)
    assert [d.outcome for d in tick(migrated_url, adapter, due + timedelta(minutes=1))] == [
        "rescheduled"
    ]
    assert fake.placed == []
    assert platform_events(migrated_url) == [failover.CARRIER_DOWN]


def test_a_carrier_that_times_out_counts_against_it(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee = instant(api, migrated_url)
    lead_in(migrated_url, employee, PHONES[0], now=NOW)
    fake.timeout_next = True
    assert [d.outcome for d in tick(migrated_url, adapter, NOW + timedelta(minutes=1))] == ["held"]
    assert sql(migrated_url, "SELECT count(*) FROM provider_outcomes WHERE NOT ok") == 1


def test_one_refused_call_is_not_the_carriers_fault(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee = instant(api, migrated_url, channels=5)
    for phone in PHONES[:3]:
        lead_in(migrated_url, employee, phone, now=NOW)
    fake.refuse_with = 400  # a number the carrier will not ring, say
    due = NOW + timedelta(minutes=1)
    assert [d.outcome for d in tick(migrated_url, adapter, due)] == ["failed"] * 3
    fake.refuse_with = 0
    lead_in(migrated_url, employee, PHONES[3], now=due)
    assert [d.outcome for d in tick(migrated_url, adapter, due + timedelta(minutes=1))] == [
        "dialed"
    ]
    outcomes = sql(migrated_url, "SELECT string_agg(ok::text, ',') FROM provider_outcomes")
    assert outcomes == "true"  # the refusals were not counted; the dial that went through was


def test_a_campaign_waits_with_a_plain_note(
    api: TestClient,
    migrated_url: str,
    carrier: tuple[Carrier, VobizTelephony],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, ["9876543210", "9876543211"])
    failures(migrated_url, "telephony", "vobiz")
    assert campaign_tick(migrated_url, adapter, NOW) == [] and fake.placed == []
    body = api.get(f"/campaigns/{campaign}", headers=owner).json()
    assert body["status"] == "running" and body["note"] == failover.CARRIER_DOWN
    later = NOW + health.WINDOW + timedelta(minutes=1)
    assert len(campaign_tick(migrated_url, adapter, later)) == 2
    assert api.get(f"/campaigns/{campaign}", headers=owner).json()["note"] is None


def test_an_incoming_call_is_missed_with_a_reason_and_called_back(
    api: TestClient,
    migrated_url: str,
    carrier: tuple[Carrier, VobizTelephony],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake, _ = carrier
    inbound_employee(api, migrated_url, channel="instant")
    failures(migrated_url, "telephony", "vobiz")  # dialing out is down; answering is not
    assert ring(migrated_url, fake, carrier_id="leg-1").kind == "answer"
    monkeypatch.delenv("SARVAM_API_KEY")
    missed = ring(migrated_url, fake, carrier_id="leg-2")
    assert (missed.kind, missed.code) == ("missed", "unavailable")
    assert missed.reason == (
        "no speech-to-text provider is working right now; calls resume when one does"
    )
    callback = "SELECT count(*) FROM calls WHERE callback_of_id = :c AND status = 'queued'"
    assert sql(migrated_url, callback, {"c": missed.call_id}) == 1
