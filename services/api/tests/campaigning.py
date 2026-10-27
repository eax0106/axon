"""Shared by the campaign tests: a Bulk employee that can dial, campaigns made through the API, the
scheduler walked through simulated time, and calls ended the way the carrier reports them."""

import uuid
from datetime import datetime
from typing import Any

from fastapi.testclient import TestClient

from app.campaigns import runner
from app.instant import dialer
from app.providers.telephony.vobiz import VobizTelephony

from .conftest import sql
from .dialing import NOW, Carrier
from .helpers import live_employee, run_db, signup

__all__ = ["NOW", "Carrier", "end_call", "make_campaign", "setup_bulk", "tick"]
PHONES = [f"98765432{i:02d}" for i in range(10, 40)]
ANSWERED = {"billsec": 30, "duration": 35, "hangup_cause": "NORMAL_CLEARING"}


def setup_bulk(
    api: TestClient,
    url: str,
    *,
    variables: tuple[str, ...] = (),
    channels: int = 5,
    number_type: str = "140",
    email: str = "owner@example.com",
    number: str = "+911400000001",
) -> tuple[str, dict[str, str]]:
    """A signed-up owner and a live Bulk employee on a 140 number (the type promotional calls may
    use) with `channels` lines."""
    owner = signup(api, email=email)
    employee = live_employee(api, url, owner, variables=variables, channel="bulk", number=number)
    sql(
        url,
        "UPDATE numbers SET number_type = :t, channels = :c WHERE e164 = :n",
        {"t": number_type, "c": channels, "n": number},
    )
    return employee, owner


def make_campaign(
    api: TestClient,
    owner: dict[str, str],
    employee: str,
    phones: list[str] | None = None,
    *,
    start: bool = True,
    consent: bool = True,
    name: str = "Diwali offer",
    **settings: Any,
) -> str:
    """A campaign made through the API: `phones` pasted in, the owner's consent, and started."""
    made = api.post(
        "/campaigns",
        json={"employee_id": employee, "name": name, "settings": settings},
        headers=owner,
    )
    assert made.status_code == 201, made.text
    campaign = str(made.json()["id"])
    if phones:
        added = api.post(
            f"/campaigns/{campaign}/contacts/import",
            json={"format": "paste", "text": "\n".join(phones)},
            headers=owner,
        )
        assert added.status_code == 200, added.text
    if consent:
        assert (
            api.post(
                f"/campaigns/{campaign}/consent", json={"confirm": True}, headers=owner
            ).status_code
            == 201
        )
    if start:
        started = api.post(f"/campaigns/{campaign}/start", headers=owner)
        assert started.status_code == 200, started.text
    return campaign


def tick(url: str, adapter: VobizTelephony, now: datetime) -> list[dialer.Dialed]:
    async def work(factory: Any) -> list[dialer.Dialed]:
        return await runner.tick(factory, adapter, now)

    return run_db(url, work)  # type: ignore[no-any-return]


def leg_of(url: str, call_id: Any) -> str:
    request_id = sql(url, "SELECT carrier_call_id FROM calls WHERE id = :c", {"c": call_id})
    return str(request_id).replace("req-", "leg-")


def end_call(
    url: str,
    fake: Carrier,
    adapter: VobizTelephony,
    call_id: Any,
    now: datetime,
    *,
    answered: bool = False,
) -> str:
    """The carrier reports the call over (answered or not); the call is settled from its record."""
    leg = leg_of(url, call_id)
    if answered:
        fake.cdr[leg] = dict(ANSWERED)

    async def work(factory: Any) -> str:
        return await dialer.settle_from_carrier(factory, adapter, call_id, now, leg_id=leg)

    return run_db(url, work)  # type: ignore[no-any-return]


def open_calls(url: str) -> list[uuid.UUID]:
    async def work(factory: Any) -> list[uuid.UUID]:
        from sqlalchemy import select

        from app.models import Call, CallStatus, CampaignContact

        async with factory() as session:
            return list(
                await session.scalars(
                    select(Call.id)
                    .join(CampaignContact, CampaignContact.id == Call.contact_id)
                    .where(Call.status == CallStatus.RINGING)
                    .order_by(CampaignContact.created_at)
                )
            )

    return run_db(url, work)  # type: ignore[no-any-return]


def contacts_by_status(url: str) -> dict[str, int]:
    async def work(factory: Any) -> dict[str, int]:
        from sqlalchemy import func, select

        from app.models import CampaignContact

        async with factory() as session:
            rows = await session.execute(
                select(CampaignContact.status, func.count()).group_by(CampaignContact.status)
            )
            return {s.value: n for s, n in rows.all()}

    return run_db(url, work)  # type: ignore[no-any-return]


def signup_second(api: TestClient) -> dict[str, str]:
    return signup(api, email="other@example.com", account="Other")


def contact_rows(url: str) -> list[tuple[str, str, int, datetime | None, str | None]]:
    """(phone, status, attempts, next_attempt_at, reason) of every contact, in upload order."""

    async def work(factory: Any) -> Any:
        from sqlalchemy import select

        from app.models import CampaignContact

        async with factory() as session:
            rows = await session.scalars(
                select(CampaignContact).order_by(CampaignContact.created_at, CampaignContact.id)
            )
            return [
                (c.phone, c.status.value, c.attempts, c.next_attempt_at, c.reason) for c in rows
            ]

    return run_db(url, work)  # type: ignore[no-any-return]


def states(url: str) -> dict[str, str]:
    return {phone: status for phone, status, *_ in contact_rows(url)}
