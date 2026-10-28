import json
import time
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.developer import delivery

from .conftest import sql
from .developer_support import (
    NOW,
    Receiver,
    announce,
    deliveries,
    make_webhook,
    tick,
    verify,
)
from .helpers import account_id, run_db, signup


def setup(
    api: TestClient, receiver: type[Receiver], url: str, path: str = "/hook"
) -> tuple[dict[str, str], dict[str, Any], Any]:
    owner = signup(api)
    hook = make_webhook(api, owner, receiver.base + path)
    return owner, hook, account_id(api, owner)


def test_a_send_is_signed_so_the_receiver_can_verify_it_and_names_the_event(
    api: TestClient, receiver: type[Receiver], migrated_url: str
) -> None:
    _, hook, account = setup(api, receiver, migrated_url)
    event_id = announce(migrated_url, account)
    tick(migrated_url)

    (sent,) = receiver.seen
    headers = sent["headers"]
    assert verify(hook["secret"], headers["X-Axon-Signature"], sent["body"])
    assert not verify("whsec_wrong", headers["X-Axon-Signature"], sent["body"])
    assert abs(int(headers["X-Axon-Signature"].split(",")[0][2:]) - time.time()) < 60
    assert headers["X-Axon-Event"] == "call.completed"
    assert headers["Content-Type"] == "application/json"
    (row,) = deliveries(migrated_url)
    assert headers["X-Axon-Delivery"] == str(row["id"])
    body = json.loads(sent["body"])
    assert body["id"] == str(event_id) and body["type"] == "call.completed"
    assert body["account_id"] == str(account) and body["data"]["call"]["status"] == "completed"
    assert "test" not in body
    # tampering with the body breaks the signature
    assert not verify(hook["secret"], headers["X-Axon-Signature"], sent["body"] + b" ")
    assert row["status"] == "delivered" and row["attempts"] == 1 and row["response_code"] == 200


def test_a_failed_send_is_retried_on_the_ladder_until_it_gets_through(
    api: TestClient, receiver: type[Receiver], migrated_url: str
) -> None:
    _, _, account = setup(api, receiver, migrated_url)
    receiver.answers = [500, 503]
    announce(migrated_url, account)
    tick(migrated_url, NOW)
    (row,) = deliveries(migrated_url)
    assert row["status"] == "pending" and row["attempts"] == 1 and row["response_code"] == 500
    assert row["next_attempt_at"] == NOW + timedelta(seconds=delivery.RETRY_AFTER_S[0])

    tick(migrated_url, NOW + timedelta(seconds=30))  # not due yet
    assert len(receiver.seen) == 1

    second = NOW + timedelta(seconds=delivery.RETRY_AFTER_S[0])
    tick(migrated_url, second)
    (row,) = deliveries(migrated_url)
    assert row["attempts"] == 2 and row["response_code"] == 503
    assert row["next_attempt_at"] == second + timedelta(seconds=delivery.RETRY_AFTER_S[1])

    tick(migrated_url, row["next_attempt_at"])
    (row,) = deliveries(migrated_url)
    assert row["status"] == "delivered" and row["attempts"] == 3 and row["last_error"] is None
    assert row["next_attempt_at"] is None and len(receiver.seen) == 3
    assert len({r["headers"]["X-Axon-Delivery"] for r in receiver.seen}) == 1  # one delivery


def test_after_the_last_attempt_a_delivery_is_failed_and_never_sent_again(
    api: TestClient, receiver: type[Receiver], migrated_url: str
) -> None:
    _, _, account = setup(api, receiver, migrated_url)
    receiver.answers = [500] * 20
    announce(migrated_url, account)
    now = NOW
    for _ in range(delivery.MAX_ATTEMPTS + 3):
        tick(migrated_url, now)
        now += timedelta(hours=7)
    (row,) = deliveries(migrated_url)
    assert row["status"] == "failed" and row["attempts"] == delivery.MAX_ATTEMPTS
    assert row["next_attempt_at"] is None and row["last_error"] == "the receiver answered 500"
    assert len(receiver.seen) == delivery.MAX_ATTEMPTS


def test_a_redirect_is_not_followed_and_counts_as_a_failure(
    api: TestClient, receiver: type[Receiver], migrated_url: str
) -> None:
    _, _, account = setup(api, receiver, migrated_url, path="/redirect")
    announce(migrated_url, account)
    tick(migrated_url)
    (row,) = deliveries(migrated_url)
    assert row["response_code"] == 302 and row["last_error"] == "the receiver answered 302"
    assert len(receiver.seen) == 1  # nobody went to the Location


def test_an_address_inside_a_network_is_refused_and_recorded(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    make_webhook(api, owner, "https://127.0.0.1/hook")  # a valid address in form, not allowed
    account = account_id(api, owner)
    announce(migrated_url, account)
    tick(migrated_url)
    (row,) = deliveries(migrated_url)
    assert row["response_code"] is None and row["last_error"] == "that address is not allowed"
    assert row["status"] == "pending" and row["attempts"] == 1  # a name can change; it is retried


def test_a_claimed_send_that_never_reports_is_tried_again_after_the_lease(
    api: TestClient, receiver: type[Receiver], migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, account = setup(api, receiver, migrated_url)
    announce(migrated_url, account)
    real = delivery.send

    async def dies(*_: object) -> delivery.Sent:
        raise RuntimeError("the worker died here")

    monkeypatch.setattr(delivery, "send", dies)
    tick(migrated_url, NOW)
    (row,) = deliveries(migrated_url)
    assert row["status"] == "pending" and row["attempts"] == 0
    assert row["next_attempt_at"] == NOW + delivery.LEASE  # leased: nobody else takes it now

    monkeypatch.setattr(delivery, "send", real)
    tick(migrated_url, NOW + timedelta(minutes=1))
    assert receiver.seen == []
    tick(migrated_url, NOW + delivery.LEASE)
    assert len(receiver.seen) == 1 and deliveries(migrated_url)[0]["status"] == "delivered"


def test_an_endpoint_that_is_switched_off_or_removed_is_never_called(
    api: TestClient, receiver: type[Receiver], migrated_url: str
) -> None:
    owner, hook, account = setup(api, receiver, migrated_url)
    announce(migrated_url, account)
    # fan out only (no send yet), then switch the endpoint off
    sql(migrated_url, "UPDATE webhook_endpoints SET active = false")

    async def fan(factory: Any) -> int:
        return await delivery.fan_out(factory, NOW)

    assert run_db(migrated_url, fan) == 1
    assert deliveries(migrated_url) == []  # nothing was made for a switched-off endpoint

    sql(migrated_url, "UPDATE webhook_endpoints SET active = true")
    announce(migrated_url, account)
    assert run_db(migrated_url, fan) == 1 and len(deliveries(migrated_url)) == 1
    sql(migrated_url, "UPDATE webhook_endpoints SET active = false")
    tick(migrated_url)
    (row,) = deliveries(migrated_url)
    assert row["status"] == "failed" and row["last_error"] == "the endpoint is switched off"

    announce(migrated_url, account)
    sql(migrated_url, "UPDATE webhook_endpoints SET active = true")
    assert run_db(migrated_url, fan) == 1
    api.delete(f"/developer/webhooks/{hook['id']}", headers=owner)
    tick(migrated_url)
    assert receiver.seen == [] and deliveries(migrated_url) == []  # they went with the endpoint


def test_an_edited_address_and_a_rotated_secret_reach_the_waiting_retries(
    api: TestClient, receiver: type[Receiver], migrated_url: str
) -> None:
    owner, hook, account = setup(api, receiver, migrated_url, path="/old")
    receiver.answers = [500]
    announce(migrated_url, account)
    tick(migrated_url, NOW)
    api.patch(
        f"/developer/webhooks/{hook['id']}", json={"url": receiver.base + "/new"}, headers=owner
    )
    new_secret = api.post(f"/developer/webhooks/{hook['id']}/rotate-secret", headers=owner).json()[
        "secret"
    ]
    tick(migrated_url, NOW + timedelta(seconds=delivery.RETRY_AFTER_S[0]))
    first, second = receiver.seen
    assert (first["path"], second["path"]) == ("/old", "/new")
    assert verify(new_secret, second["headers"]["X-Axon-Signature"], second["body"])
    assert deliveries(migrated_url)[0]["target_url"].endswith("/new")
