import json

from fastapi.testclient import TestClient

from .developer_support import Receiver, announce, deliveries, make_webhook, tick, verify
from .helpers import account_id, add_member, signup


def two_deliveries(
    api: TestClient, receiver: type[Receiver], url: str
) -> tuple[dict[str, str], str, str]:
    owner = signup(api)
    hook = make_webhook(api, owner, receiver.base + "/hook", ["call.completed", "lead.created"])
    account = account_id(api, owner)
    announce(url, account, "call.completed")
    announce(url, account, "lead.created")
    receiver.answers = [200, 500]
    tick(url)
    return owner, hook["id"], hook["secret"]


def test_the_log_lists_deliveries_with_filters_and_shows_the_exact_payload(
    api: TestClient, receiver: type[Receiver], migrated_url: str
) -> None:
    owner, hook, _ = two_deliveries(api, receiver, migrated_url)
    page = api.get("/developer/deliveries", headers=owner).json()
    assert len(page["data"]) == 2 and page["next_cursor"] is None
    by_event = {d["event"]: d for d in page["data"]}
    assert by_event["call.completed"]["status"] == "delivered"
    assert by_event["lead.created"]["status"] == "pending"
    assert by_event["lead.created"]["response_code"] == 500
    assert by_event["lead.created"]["next_attempt_at"] is not None
    assert by_event["call.completed"]["endpoint_id"] == hook

    def ask(**params: str) -> list[str]:
        found = api.get("/developer/deliveries", params=params, headers=owner).json()["data"]
        return [d["event"] for d in found]

    assert ask(status="pending") == ["lead.created"]
    assert ask(event="call.completed") == ["call.completed"]
    assert sorted(ask(endpoint_id=hook)) == ["call.completed", "lead.created"]
    assert ask(endpoint_id="00000000-0000-0000-0000-000000000000") == []

    first = api.get("/developer/deliveries?limit=1", headers=owner).json()
    rest = api.get(f"/developer/deliveries?limit=5&cursor={first['next_cursor']}", headers=owner)
    assert len(first["data"]) == 1 and len(rest.json()["data"]) == 1

    detail = api.get(f"/developer/deliveries/{by_event['call.completed']['id']}", headers=owner)
    sent = next(r for r in receiver.seen if r["headers"]["X-Axon-Event"] == "call.completed")
    assert detail.json()["payload"] == json.loads(sent["body"])


def test_a_resend_is_a_new_delivery_of_the_same_event_and_a_pending_one_cannot_be(
    api: TestClient, receiver: type[Receiver], migrated_url: str
) -> None:
    owner, _, secret = two_deliveries(api, receiver, migrated_url)
    by_event = {
        d["event"]: d for d in api.get("/developer/deliveries", headers=owner).json()["data"]
    }
    pending, done = by_event["lead.created"], by_event["call.completed"]
    assert (
        api.post(f"/developer/deliveries/{pending['id']}/resend", headers=owner).status_code == 409
    )

    again = api.post(f"/developer/deliveries/{done['id']}/resend", headers=owner)
    assert again.status_code == 201 and again.json()["id"] != done["id"]
    assert again.json()["event_id"] == done["event_id"] and again.json()["status"] == "pending"
    before = len(receiver.seen)
    tick(migrated_url)
    sent = receiver.seen[before:]
    assert len(sent) == 1 and json.loads(sent[0]["body"])["id"] == done["event_id"]
    assert verify(secret, sent[0]["headers"]["X-Axon-Signature"], sent[0]["body"])
    assert sent[0]["headers"]["X-Axon-Delivery"] == again.json()["id"]
    assert len(deliveries(migrated_url)) == 3  # the first one is still in the log


def test_resend_and_the_log_belong_to_the_account_and_resend_to_the_owner(
    api: TestClient, receiver: type[Receiver], migrated_url: str
) -> None:
    owner, _, _ = two_deliveries(api, receiver, migrated_url)
    done = api.get("/developer/deliveries?status=delivered", headers=owner).json()["data"][0]
    member = add_member(api, migrated_url, owner)
    assert api.get(f"/developer/deliveries/{done['id']}", headers=member).status_code == 200
    assert api.post(f"/developer/deliveries/{done['id']}/resend", headers=member).status_code == 403
    other = signup(api, email="b@example.com", account="Other")
    assert api.get("/developer/deliveries", headers=other).json()["data"] == []
    assert api.get(f"/developer/deliveries/{done['id']}", headers=other).status_code == 404
    assert api.post(f"/developer/deliveries/{done['id']}/resend", headers=other).status_code == 404


def test_the_test_button_sends_an_example_at_once_and_reports_the_answer(
    api: TestClient, receiver: type[Receiver], migrated_url: str
) -> None:
    owner = signup(api)
    hook = make_webhook(api, owner, receiver.base + "/hook")
    url = f"/developer/webhooks/{hook['id']}/test"

    ok = api.post(url, json={"event": "campaign.status_changed"}, headers=owner).json()
    assert ok["delivered"] is True and ok["response_code"] == 200 and ok["error"] is None
    (sent,) = receiver.seen
    body = json.loads(sent["body"])
    assert body["test"] is True and body["type"] == "campaign.status_changed"
    assert body["data"]["campaign"]["status"] == "running"
    assert sent["headers"]["X-Axon-Event"] == "campaign.status_changed"
    assert verify(hook["secret"], sent["headers"]["X-Axon-Signature"], sent["body"])

    receiver.answers = [500]
    bad = api.post(url, json={}, headers=owner).json()
    assert bad["delivered"] is False and bad["response_code"] == 500 and bad["error"]
    tick(migrated_url)  # a test is not retried and fan-out does not send it again
    assert len(receiver.seen) == 2
    rows = deliveries(migrated_url)
    assert [r["is_test"] for r in rows] == [True, True]
    assert [r["status"] for r in rows] == ["delivered", "failed"]
    assert api.post(url, json={"event": "nope"}, headers=owner).status_code == 422
    api.patch(f"/developer/webhooks/{hook['id']}", json={"active": False}, headers=owner)
    assert api.post(url, json={}, headers=owner).json()["delivered"] is True  # off still tests
