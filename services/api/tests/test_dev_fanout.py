import asyncio
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.developer import delivery

from .conftest import sql
from .developer_support import NOW, Receiver, announce, deliveries, events_of, make_webhook
from .helpers import account_id, live_employee, run_db, signup
from .test_result_webhook import call_event, hook, publish, set_hook


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


def fan_selects(url: str) -> tuple[int, int]:
    """Fan out once; returns how many events were taken and how many SELECTs that cost."""

    async def go() -> tuple[int, int]:
        engine = create_async_engine(url)
        selects: list[str] = []

        def record(*args: Any) -> None:
            if args[2].lstrip().upper().startswith("SELECT"):
                selects.append(args[2])

        event.listen(engine.sync_engine, "before_cursor_execute", record)
        try:
            taken = await delivery.fan_out(async_sessionmaker(engine, expire_on_commit=False), NOW)
            return taken, len(selects)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def test_a_batch_of_events_is_matched_in_the_same_queries_as_one_event(
    api: TestClient, migrated_url: str, receiver: type[Receiver]
) -> None:
    owner = signup(api)
    account = account_id(api, owner)
    calls = make_webhook(api, owner, "https://a.example.com/x", ["call.completed"])
    leads = make_webhook(api, owner, "https://b.example.com/x", ["lead.created"])
    hooked = live_employee(api, migrated_url, owner)
    plain = live_employee(api, migrated_url, owner, number="+911400000002")
    set_hook(api, owner, hooked, hook(receiver.base))
    publish(api, owner, hooked)
    other = signup(api, email="b@example.com", account="Other")
    theirs = make_webhook(api, other, "https://c.example.com/x", ["call.completed"])

    call_event(migrated_url, account, hooked)
    taken, one = fan_selects(migrated_url)
    assert taken == 1

    first = announce(migrated_url, account, "call.completed", employee=hooked)
    second = announce(migrated_url, account, "call.completed", employee=plain)
    lead = announce(migrated_url, account, "lead.created")
    missed = announce(migrated_url, account, "call.not_connected", employee=hooked)
    foreign = announce(migrated_url, account_id(api, other), "call.completed")
    taken, five = fan_selects(migrated_url)
    assert taken == 5
    assert five == one, "the batch must not cost queries per event"

    made: dict[str, set[str]] = {}
    for d in deliveries(migrated_url):
        made.setdefault(str(d["event_id"]), set()).add(
            str(d["endpoint_id"]) if d["endpoint_id"] else f"hook:{d['employee_id']}"
        )
    assert made[str(first)] == {calls["id"], f"hook:{hooked}"}
    assert made[str(second)] == {calls["id"]}  # no published hook
    assert made[str(lead)] == {leads["id"]}
    assert str(missed) not in made  # nobody subscribed, and a hook only wants connected calls
    assert made[str(foreign)] == {theirs["id"]}  # never another account's endpoints
