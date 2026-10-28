import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.developer import events, router

from .developer_support import Receiver, make_webhook, verify
from .helpers import add_member, signup

URL = "https://hooks.example.com/axon"


def test_an_endpoint_is_created_with_a_secret_that_is_shown_only_then(api: TestClient) -> None:
    owner = signup(api)
    created = make_webhook(api, owner, URL, ["call.completed", "lead.created"])
    assert created["secret"].startswith("whsec_") and len(created["secret"]) > 30
    assert created["active"] is True and created["events"] == ["call.completed", "lead.created"]
    shown = api.get(f"/developer/webhooks/{created['id']}", headers=owner).json()
    listed = api.get("/developer/webhooks", headers=owner).json()
    assert "secret" not in shown and created["secret"] not in str(listed)
    assert [w["id"] for w in listed] == [created["id"]]


@pytest.mark.parametrize(
    ("body", "why"),
    [
        ({"url": "http://hooks.example.com/x", "events": ["call.completed"]}, "https"),
        ({"url": "https://hooks.example.com:8443/x", "events": ["call.completed"]}, "port"),
        ({"url": "https://user:pw@hooks.example.com/x", "events": ["call.completed"]}, "login"),
        ({"url": "not a url", "events": ["call.completed"]}, "https"),
        ({"url": URL, "events": ["call.exploded"]}, "unknown event"),
        ({"url": URL, "events": []}, "at least one"),
        ({"url": URL, "events": ["call.completed", "call.completed"]}, "each once"),
        ({"url": URL, "events": ["test.ping"]}, "unknown event"),
        ({"url": URL}, "events"),
    ],
)
def test_a_bad_address_or_event_is_refused_with_a_reason(
    api: TestClient, body: dict[str, Any], why: str
) -> None:
    owner = signup(api)
    refused = api.post("/developer/webhooks", json=body, headers=owner)
    assert refused.status_code == 422 and why in refused.text
    assert api.get("/developer/webhooks", headers=owner).json() == []


def test_an_endpoint_can_be_edited_switched_off_and_deleted(api: TestClient) -> None:
    owner = signup(api)
    hook = make_webhook(api, owner, URL)
    url = f"/developer/webhooks/{hook['id']}"
    edited = api.patch(
        url,
        json={"events": ["call.not_connected"], "active": False, "description": "CRM"},
        headers=owner,
    ).json()
    assert edited["events"] == ["call.not_connected"] and edited["active"] is False
    assert edited["description"] == "CRM" and edited["url"] == URL
    assert api.patch(url, json={"url": "http://x.example.com"}, headers=owner).status_code == 422
    assert api.patch(url, json={"events": None}, headers=owner).status_code == 422
    assert api.patch(url, json={"description": None}, headers=owner).json()["description"] is None
    assert api.delete(url, headers=owner).status_code == 204
    assert api.get(url, headers=owner).status_code == 404


def test_the_number_of_endpoints_is_capped(api: TestClient) -> None:
    owner = signup(api)
    for i in range(router.MAX_ENDPOINTS):
        make_webhook(api, owner, f"https://hooks.example.com/{i}")
    full = api.post(
        "/developer/webhooks", json={"url": URL, "events": ["call.completed"]}, headers=owner
    )
    assert full.status_code == 409


def test_only_the_owner_changes_endpoints_and_nobody_reaches_another_accounts(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    member = add_member(api, migrated_url, owner)
    hook = make_webhook(api, owner, URL)
    url = f"/developer/webhooks/{hook['id']}"
    body = {"url": URL, "events": ["call.completed"]}
    assert api.post("/developer/webhooks", json=body, headers=member).status_code == 403
    assert api.patch(url, json={"active": False}, headers=member).status_code == 403
    assert api.delete(url, headers=member).status_code == 403
    assert api.post(f"{url}/rotate-secret", headers=member).status_code == 403
    assert api.post(f"{url}/test", json={}, headers=member).status_code == 403
    assert api.get(url, headers=member).status_code == 200

    other = signup(api, email="b@example.com", account="Other")
    assert api.get("/developer/webhooks", headers=other).json() == []
    for call in (
        api.get(url, headers=other),
        api.patch(url, json={"active": False}, headers=other),
        api.delete(url, headers=other),
        api.post(f"{url}/rotate-secret", headers=other),
        api.post(f"{url}/test", json={}, headers=other),
        api.get(f"/developer/webhooks/{uuid.uuid4()}", headers=owner),
    ):
        assert call.status_code == 404


def test_rotating_the_secret_changes_how_the_next_send_is_signed(
    api: TestClient, receiver: type[Receiver]
) -> None:
    owner = signup(api)
    hook = make_webhook(api, owner, receiver.base + "/hook")
    url = f"/developer/webhooks/{hook['id']}"

    api.post(f"{url}/test", json={}, headers=owner)
    sent = receiver.seen[0]
    assert verify(hook["secret"], sent["headers"]["X-Axon-Signature"], sent["body"])

    new = api.post(f"{url}/rotate-secret", headers=owner).json()["secret"]
    assert new.startswith("whsec_") and new != hook["secret"]
    api.post(f"{url}/test", json={}, headers=owner)
    sent = receiver.seen[1]
    assert verify(new, sent["headers"]["X-Axon-Signature"], sent["body"])
    assert not verify(hook["secret"], sent["headers"]["X-Axon-Signature"], sent["body"])
    assert "secret" not in api.get(url, headers=owner).json()


def test_the_event_list_gives_every_event_an_example(api: TestClient) -> None:
    owner = signup(api)
    listed = api.get("/developer/events", headers=owner).json()
    assert [e["type"] for e in listed] == list(events.EVENT_TYPES)
    assert all(e["description"] and e["example"] for e in listed)
