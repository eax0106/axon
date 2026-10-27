import asyncio
from typing import Any

from fastapi.testclient import TestClient

from app.developer import delivery

from .conftest import sql
from .developer_support import NOW, announce, deliveries, events_of, make_webhook
from .helpers import account_id, run_db, signup


def fan(url: str) -> int:
    async def work(factory: Any) -> int:
        return await delivery.fan_out(factory, NOW)

    taken: int = run_db(url, work)
    return taken


def test_an_event_goes_to_every_active_subscribed_endpoint_of_its_account_and_no_other(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    account = account_id(api, owner)
    both = make_webhook(api, owner, "https://a.example.com/x", ["call.completed", "lead.created"])
    only_calls = make_webhook(api, owner, "https://b.example.com/x", ["call.completed"])
    make_webhook(api, owner, "https://c.example.com/x", ["lead.created"])  # other event
    off = make_webhook(api, owner, "https://d.example.com/x", ["call.completed"])
    api.patch(f"/developer/webhooks/{off['id']}", json={"active": False}, headers=owner)
    stranger = signup(api, email="b@example.com", account="Other")
    make_webhook(api, stranger, "https://e.example.com/x", ["call.completed"])

    event_id = announce(migrated_url, account, "call.completed")
    assert fan(migrated_url) == 1
    made = deliveries(migrated_url)
    assert sorted(str(d["endpoint_id"]) for d in made) == sorted([both["id"], only_calls["id"]])
    assert {str(d["account_id"]) for d in made} == {account}
    assert all(d["status"] == "pending" and d["attempts"] == 0 for d in made)
    assert all(d["payload"]["id"] == str(event_id) for d in made)
    assert made[0]["payload"] == made[1]["payload"]
    assert {d["event"] for d in made} == {"call.completed"}


def test_an_event_with_nobody_listening_makes_no_delivery_and_is_still_taken(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    announce(migrated_url, account_id(api, owner), "lead.created")
    assert fan(migrated_url) == 1
    assert deliveries(migrated_url) == []
    assert events_of(migrated_url)[0]["fanned_out_at"] is not None


def test_an_event_is_fanned_out_once_even_with_two_workers_at_the_same_time(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    account = account_id(api, owner)
    make_webhook(api, owner, "https://a.example.com/x")
    for _ in range(30):
        announce(migrated_url, account, "call.completed")

    async def two(factory: Any) -> list[int]:
        return list(
            await asyncio.gather(delivery.fan_out(factory, NOW), delivery.fan_out(factory, NOW))
        )

    run_db(migrated_url, two)
    assert fan(migrated_url) <= 30  # whatever the two left is taken now
    assert fan(migrated_url) == 0
    assert len(deliveries(migrated_url)) == 30
    assert sql(migrated_url, "SELECT count(DISTINCT event_id) FROM webhook_deliveries") == 30
