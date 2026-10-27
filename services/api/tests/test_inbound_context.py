"""An Instant or Bulk employee answers its own leads' call backs, knowing why they ring."""

import uuid
from typing import Any

from fastapi.testclient import TestClient

from app.inbound import plan
from app.models import Call, Employee, Lead

from .campaigning import make_campaign, setup_bulk
from .conftest import sql
from .dialing import Carrier
from .helpers import run_db
from .inbound_support import NUMBER, inbound_employee, ring
from .test_inbound_callback import CLOSED

BULK_NUMBER = "+911400000001"


def extras_of(url: str, call_id: Any) -> plan.Extras | None:
    async def work(factory: Any) -> plan.Extras | None:
        async with factory() as session:
            call = await session.get(Call, uuid.UUID(str(call_id)))
            assert call is not None and call.employee_id is not None
            employee = await session.get(Employee, call.employee_id)
            assert employee is not None
            lead = await session.get(Lead, call.lead_id) if call.lead_id else None
            return await plan.extras(session, employee, call, lead)

    out: plan.Extras | None = run_db(url, work)
    return out


def test_an_instant_employee_picks_up_and_knows_what_was_said_last_time(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    inbound_employee(api, migrated_url, channel="instant")
    sql(migrated_url, "UPDATE employees SET name = 'Asha'")
    first = ring(migrated_url, fake, carrier_id="leg-1")
    assert first.kind == "answer"
    sql(
        migrated_url,
        "UPDATE calls SET status = 'completed', ended_at = now(), summary = 'Wanted a solar quote'",
    )
    second = ring(migrated_url, fake, carrier_id="leg-2")
    assert second.kind == "answer"
    added = extras_of(migrated_url, second.call_id)
    assert added is not None
    assert added.context.incoming and added.opening and added.opening == added.context.opening
    assert added.context.notes == ("Their last call with you: Wanted a solar quote",)
    assert added.transfer_to is None and added.context.transfer_when is None


def test_a_transfer_number_gives_the_call_a_person_to_hand_over_to(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    inbound_employee(
        api,
        migrated_url,
        channel="instant",
        settings={"transfer_number": "+919811112222", "transfer_when": "They ask for the owner."},
    )
    routed = ring(migrated_url, fake)
    added = extras_of(migrated_url, routed.call_id)
    assert added is not None
    assert added.transfer_to == "+919811112222" and added.caller_id == NUMBER
    assert added.context.transfer_when == "They ask for the owner."


def test_a_bulk_employee_knows_the_row_of_its_own_list_the_caller_came_from(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    employee, owner = setup_bulk(api, migrated_url, variables=("city",))
    make_campaign(api, owner, employee, ["9876543210"], start=False)
    sql(
        migrated_url,
        "UPDATE campaign_contacts SET variables = CAST(:v AS jsonb)",
        {"v": '{"city": "Pune"}'},
    )
    routed = ring(migrated_url, fake, to=BULK_NUMBER)
    assert routed.kind == "answer", routed.reason
    added = extras_of(migrated_url, routed.call_id)
    assert added is not None and added.variables == {"city": "Pune"}


def test_a_call_we_make_to_a_missed_caller_is_told_it_is_a_call_back(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    inbound_employee(api, migrated_url, settings=CLOSED)
    missed = ring(migrated_url, fake)
    back = sql(migrated_url, "SELECT id FROM calls WHERE is_callback")
    added = extras_of(migrated_url, back)
    assert missed.kind == "missed" and added is not None
    assert added.context.notes == (plan.CALLED_BACK,) and not added.context.incoming
    assert added.opening == ""


def test_an_ordinary_outbound_call_and_a_test_call_add_nothing(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    inbound_employee(api, migrated_url, channel="instant")
    routed = ring(migrated_url, fake)
    sql(migrated_url, "UPDATE calls SET direction = 'outbound'")
    assert extras_of(migrated_url, routed.call_id) is None
    sql(migrated_url, "UPDATE calls SET direction = 'inbound', is_test = true")
    assert extras_of(migrated_url, routed.call_id) is None


def test_the_caller_of_a_number_that_is_not_the_employees_to_answer_is_missed_with_a_reason(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, None]
) -> None:
    fake, _ = carrier
    inbound_employee(api, migrated_url, channel="instant", settings={"answer_callbacks": False})
    routed = ring(migrated_url, fake)
    assert routed.kind == "missed" and routed.code == "no_callbacks"
    assert routed.reason is not None
