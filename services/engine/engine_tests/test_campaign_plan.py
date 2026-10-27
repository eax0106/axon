"""A campaign call speaks to its contact: the row of the uploaded list fills the script."""

import asyncio
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine
from tests.campaigning import NOW, Carrier, make_campaign, setup_bulk, tick
from tests.conftest import sql

from app.providers.telephony.vobiz import VobizTelephony
from engine.plan import load_plan


def plan_of(url: str, employee: str, call: str) -> Any:
    async def go() -> Any:
        engine = create_async_engine(url)
        try:
            return await load_plan(engine, employee, call)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def test_the_call_to_a_contact_is_told_the_contacts_name_and_variables(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    _, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url, variables=("city",))
    api.put(
        f"/employees/{employee}/script",
        json={"welcome_message": "Hello {{name}} from {{city}}", "pre_call_variables": ["city"]},
        headers=owner,
    )
    api.post(f"/employees/{employee}/publish", headers=owner)
    campaign = make_campaign(api, owner, employee, None, start=False, consent=False)
    api.post(
        f"/campaigns/{campaign}/contacts",
        json=[{"phone": "9876543210", "name": "Ravi", "variables": {"city": "Pune"}}],
        headers=owner,
    )
    api.post(f"/campaigns/{campaign}/consent", json={"confirm": True}, headers=owner)
    api.post(f"/campaigns/{campaign}/start", headers=owner)
    # The account already knew this number from another source, with a different city.
    account = sql(migrated_url, "SELECT account_id FROM employees")
    sql(
        migrated_url,
        "INSERT INTO leads (account_id, phone, name, fields)"
        " VALUES (:a, '+919876543210', 'Old name', '{\"city\": \"Goa\"}')",
        {"a": account},
    )
    tick(migrated_url, adapter, NOW)
    call = str(sql(migrated_url, "SELECT id FROM calls"))
    plan = plan_of(migrated_url, employee, call)
    assert plan is not None
    assert "Ravi" in plan.system_prompt and "Pune" in plan.system_prompt
    assert "Goa" not in plan.system_prompt  # the contact's own row wins over the older lead


def test_a_call_id_of_another_employee_does_not_lend_its_contact(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    _, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url, variables=("city",))
    api.put(
        f"/employees/{employee}/script",
        json={"welcome_message": "Hello {{name}} from {{city}}", "pre_call_variables": ["city"]},
        headers=owner,
    )
    api.post(f"/employees/{employee}/publish", headers=owner)
    make_campaign(api, owner, employee, ["9876543210"])
    tick(migrated_url, adapter, NOW)
    call = str(sql(migrated_url, "SELECT id FROM calls"))
    other = api.post("/employees", json={"channel": "bulk", "name": "Other"}, headers=owner).json()
    api.post(f"/employees/{other['id']}/publish", headers=owner)
    plan = plan_of(migrated_url, other["id"], call)
    assert plan is not None and "+919876543210" not in plan.system_prompt
