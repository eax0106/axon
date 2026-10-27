"""Concurrent callers are limited by the channels of the number."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import PhoneNumber
from app.numbers import channels

from .conftest import sql
from .dialing import Carrier
from .helpers import run_db
from .inbound_support import calls, inbound_employee, ring


def busy_now(url: str) -> int:
    async def work(factory: Any) -> int:
        async with factory() as session:
            number_id = await session.scalar(select(PhoneNumber.id))
            return await channels.busy(session, number_id)

    out: int = run_db(url, work)
    return out


def test_the_caller_who_finds_every_channel_busy_is_missed_as_busy(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    inbound_employee(api, migrated_url)
    first = ring(migrated_url, fake, carrier_id="leg-1", caller="+919876543211")
    second = ring(migrated_url, fake, carrier_id="leg-2", caller="+919876543212")
    assert first.kind == "answer"
    assert second.kind == "missed" and second.code == "busy"
    assert second.reason is not None and "already on a call" in second.reason
    assert busy_now(migrated_url) == 1  # the missed call holds nothing


def test_an_answered_call_holds_a_channel_until_it_ends(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    inbound_employee(api, migrated_url)
    ring(migrated_url, fake, carrier_id="leg-1")
    assert busy_now(migrated_url) == 1
    sql(migrated_url, "UPDATE calls SET status = 'in_progress'")
    assert ring(migrated_url, fake, carrier_id="leg-2").code == "busy"
    sql(migrated_url, "UPDATE calls SET status = 'completed' WHERE carrier_leg_id = 'leg-1'")
    assert busy_now(migrated_url) == 0
    assert ring(migrated_url, fake, carrier_id="leg-3").kind == "answer"


def test_more_channels_mean_more_callers_at_once(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    inbound_employee(api, migrated_url)
    sql(migrated_url, "UPDATE numbers SET channels = 3")
    kinds = [
        ring(migrated_url, fake, carrier_id=f"leg-{n}", caller=f"+91987654321{n}").kind
        for n in range(4)
    ]
    assert kinds == ["answer", "answer", "answer", "missed"]
    assert busy_now(migrated_url) == 3
    assert len(calls(migrated_url, "direction = 'inbound'")) == 4  # the fourth is a missed caller


def test_a_call_going_out_on_the_number_takes_a_channel_too(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    inbound_employee(api, migrated_url)
    sql(
        migrated_url,
        "INSERT INTO calls (account_id, number_id, direction, channel, status)"
        " SELECT account_id, id, 'outbound', 'inbound', 'ringing' FROM numbers",
    )
    assert ring(migrated_url, fake).code == "busy"
