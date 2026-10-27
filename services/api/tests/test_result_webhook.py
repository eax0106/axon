"""An employee's result webhook: set on the draft, live only after publish, sent for the calls its
trigger wants, signed when it has a secret, and its secret never read back."""

import copy
import json
from typing import Any

from fastapi.testclient import TestClient

from app.actions.schema import MASK
from app.developer import events

from .conftest import sql
from .developer_support import Receiver, announce, deliveries, tick, verify
from .helpers import account_id, live_employee, signup
from .test_ai_builder import Vendor, vendor  # noqa: F401

SECRET = "whsec-for-the-crm"  # noqa: S105 - a test value


def hook(base: str, **fields: Any) -> dict[str, Any]:
    return {"url": f"{base}/result", **fields}


def set_hook(
    api: TestClient, owner: dict[str, str], employee: str, body: dict[str, Any]
) -> dict[str, Any]:
    response = api.put(f"/employees/{employee}/webhook", json=body, headers=owner)
    assert response.status_code == 200, response.text
    shown: dict[str, Any] = response.json()["webhook"]
    return shown


def publish(api: TestClient, owner: dict[str, str], employee: str) -> None:
    assert api.post(f"/employees/{employee}/publish", headers=owner).status_code == 200


def call_event(
    url: str,
    account: Any,
    employee: str,
    *,
    voicemail: bool = False,
    type_: str = events.CALL_COMPLETED,
) -> None:
    data = copy.deepcopy(events.sample(type_))
    data["call"]["voicemail"] = voicemail
    announce(url, account, type_, data, employee)


def setup(api: TestClient, url: str) -> tuple[dict[str, str], str, Any]:
    owner = signup(api)
    employee = live_employee(api, url, owner)
    return owner, employee, account_id(api, owner)


def result_sends(url: str, employee: str) -> list[dict[str, Any]]:
    return deliveries(url, employee_id=employee)


def test_the_draft_hook_sends_nothing_until_it_is_published(
    api: TestClient, migrated_url: str, receiver: type[Receiver]
) -> None:
    owner, employee, account = setup(api, migrated_url)
    set_hook(api, owner, employee, hook(receiver.base))
    call_event(migrated_url, account, employee)
    tick(migrated_url)
    assert receiver.seen == [] and result_sends(migrated_url, employee) == []

    publish(api, owner, employee)
    call_event(migrated_url, account, employee)
    tick(migrated_url)
    (sent,) = receiver.seen
    assert sent["path"] == "/result" and sent["headers"]["X-Axon-Event"] == "call.completed"
    assert sent["headers"].get("X-Axon-Signature") is None  # no secret, no signature
    assert receiver.bodies()[0]["data"]["call"]["voicemail"] is False


def test_the_published_version_is_what_sends_not_a_later_draft(
    api: TestClient, migrated_url: str, receiver: type[Receiver]
) -> None:
    owner, employee, account = setup(api, migrated_url)
    set_hook(api, owner, employee, hook(receiver.base))
    publish(api, owner, employee)
    set_hook(api, owner, employee, {"url": f"{receiver.base}/elsewhere"})  # an unpublished edit
    call_event(migrated_url, account, employee)
    tick(migrated_url)
    assert [r["path"] for r in receiver.seen] == ["/result"]


def test_each_trigger_picks_its_calls(
    api: TestClient, migrated_url: str, receiver: type[Receiver]
) -> None:
    owner, employee, account = setup(api, migrated_url)
    for trigger, expected in (
        ("all_connected", [False, True]),
        ("skip_voicemail", [False]),
        ("voicemail_only", [True]),
    ):
        receiver.reset()
        set_hook(api, owner, employee, hook(receiver.base, trigger=trigger))
        publish(api, owner, employee)
        call_event(migrated_url, account, employee, voicemail=False)
        call_event(migrated_url, account, employee, voicemail=True)
        tick(migrated_url)
        seen = [b["data"]["call"]["voicemail"] for b in receiver.bodies()]
        assert sorted(seen) == expected, trigger


def test_a_call_that_did_not_connect_is_never_sent(
    api: TestClient, migrated_url: str, receiver: type[Receiver]
) -> None:
    owner, employee, account = setup(api, migrated_url)
    set_hook(api, owner, employee, hook(receiver.base))
    publish(api, owner, employee)
    for type_ in (events.CALL_NOT_CONNECTED, events.INBOUND_MISSED, events.LEAD_CREATED):
        announce(migrated_url, account, type_, events.sample(type_), employee)
    call_event(migrated_url, account, employee, type_=events.INBOUND_ANSWERED)
    tick(migrated_url)
    assert [e["event"] for e in result_sends(migrated_url, employee)] == ["call.inbound_answered"]
    assert len(receiver.seen) == 1


def test_a_secret_signs_the_send(
    api: TestClient, migrated_url: str, receiver: type[Receiver]
) -> None:
    owner, employee, account = setup(api, migrated_url)
    set_hook(api, owner, employee, hook(receiver.base, secret=SECRET))
    publish(api, owner, employee)
    call_event(migrated_url, account, employee)
    tick(migrated_url)
    (sent,) = receiver.seen
    assert verify(SECRET, sent["headers"]["X-Axon-Signature"], sent["body"])
    assert not verify("another-secret", sent["headers"]["X-Axon-Signature"], sent["body"])


def test_the_secret_is_never_read_back_and_is_kept_while_the_host_stays(
    api: TestClient, migrated_url: str, receiver: type[Receiver]
) -> None:
    owner, employee, account = setup(api, migrated_url)
    shown = set_hook(api, owner, employee, hook(receiver.base, secret=SECRET))
    assert shown["secret"] == MASK

    # The editor sends back what it read: the stored secret stays, even with a new path.
    again = set_hook(api, owner, employee, {**shown, "url": f"{receiver.base}/new-path"})
    assert again["secret"] == MASK and again["url"].endswith("/new-path")
    publish(api, owner, employee)

    reads = [
        api.get(f"/employees/{employee}/webhook", headers=owner),
        api.get(f"/employees/{employee}", headers=owner),
        api.get(f"/employees/{employee}/versions", headers=owner),
    ]
    assert all(SECRET not in r.text for r in reads)
    assert reads[0].json()["webhook"]["secret"] == MASK
    assert reads[2].json()[0]["script"]["result_webhook"]["secret"] == MASK

    call_event(migrated_url, account, employee)
    tick(migrated_url)
    (sent,) = receiver.seen
    assert sent["path"] == "/new-path"
    assert verify(SECRET, sent["headers"]["X-Axon-Signature"], sent["body"])


def test_a_mask_cannot_be_used_for_another_host_or_when_nothing_is_stored(
    api: TestClient, migrated_url: str, receiver: type[Receiver]
) -> None:
    owner, employee, _ = setup(api, migrated_url)
    nothing = api.put(
        f"/employees/{employee}/webhook", json=hook(receiver.base, secret=MASK), headers=owner
    )
    assert nothing.status_code == 422 and "again" in nothing.text

    set_hook(api, owner, employee, hook(receiver.base, secret=SECRET))
    moved = api.put(
        f"/employees/{employee}/webhook",
        json={"url": "http://localhost:9/steal", "secret": MASK},
        headers=owner,
    )
    assert moved.status_code == 422 and "another host" in moved.text
    stored = sql(migrated_url, "SELECT draft FROM employees WHERE id = :e", {"e": employee})
    assert stored["result_webhook"]["secret"] == SECRET  # unchanged

    script = {
        "welcome_message": "hi",
        "result_webhook": {"url": "http://x.example/h", "secret": MASK},
    }
    assert api.put(f"/employees/{employee}/script", json=script, headers=owner).status_code == 422


def test_the_address_must_be_one_the_tool_may_call(api: TestClient, migrated_url: str) -> None:
    owner, employee, _ = setup(api, migrated_url)
    for url in ("http://insecure.example.com/h", "https://user:pw@example.com/h", "not a url"):
        response = api.put(f"/employees/{employee}/webhook", json={"url": url}, headers=owner)
        assert response.status_code == 422, url


def test_saving_the_script_without_the_field_leaves_the_hook_and_clear_removes_it(
    api: TestClient, migrated_url: str, receiver: type[Receiver]
) -> None:
    owner, employee, _ = setup(api, migrated_url)
    set_hook(api, owner, employee, hook(receiver.base, secret=SECRET))
    saved = api.put(f"/employees/{employee}/script", json={"welcome_message": "new"}, headers=owner)
    assert saved.status_code == 200
    stored = sql(migrated_url, "SELECT draft FROM employees WHERE id = :e", {"e": employee})
    assert stored["welcome_message"] == "new" and stored["result_webhook"]["secret"] == SECRET

    cleared = api.put(f"/employees/{employee}/script", json={"result_webhook": None}, headers=owner)
    assert cleared.status_code == 200
    assert api.get(f"/employees/{employee}/webhook", headers=owner).json() == {"webhook": None}

    set_hook(api, owner, employee, hook(receiver.base))
    assert api.delete(f"/employees/{employee}/webhook", headers=owner).status_code == 204
    assert api.get(f"/employees/{employee}/webhook", headers=owner).json() == {"webhook": None}


def test_the_ai_edit_flow_does_not_see_the_secret_and_its_proposal_keeps_the_hook(
    api: TestClient,
    migrated_url: str,
    receiver: type[Receiver],
    vendor: Vendor,  # noqa: F811
) -> None:
    owner, employee, _ = setup(api, migrated_url)
    set_hook(api, owner, employee, hook(receiver.base, secret=SECRET))
    vendor.text = json.dumps({"welcome_message": "edited", "sections": []})
    proposal = api.post(
        f"/employees/{employee}/ai/edit-flow", json={"instruction": "x"}, headers=owner
    )
    assert proposal.status_code == 200, proposal.text
    assert SECRET not in vendor.requests[-1].content.decode()
    assert SECRET not in proposal.text
    body = proposal.json()
    assert body["result_webhook"]["secret"] == MASK
    # Saving the proposal as the editor does keeps the stored secret.
    assert api.put(f"/employees/{employee}/script", json=body, headers=owner).status_code == 200
    stored = sql(migrated_url, "SELECT draft FROM employees WHERE id = :e", {"e": employee})
    assert stored["welcome_message"] == "edited" and stored["result_webhook"]["secret"] == SECRET


def test_versions_carry_the_hook_and_a_restore_brings_it_back(
    api: TestClient, migrated_url: str, receiver: type[Receiver]
) -> None:
    owner, employee, account = setup(api, migrated_url)
    set_hook(api, owner, employee, hook(receiver.base, secret=SECRET))
    publish(api, owner, employee)
    version = api.get(f"/employees/{employee}/versions", headers=owner).json()[0]["version"]

    api.delete(f"/employees/{employee}/webhook", headers=owner)
    publish(api, owner, employee)
    call_event(migrated_url, account, employee)
    tick(migrated_url)
    assert receiver.seen == []  # the live version has no hook any more

    restored = api.post(f"/employees/{employee}/versions/{version}/restore", headers=owner)
    assert restored.status_code == 200
    assert api.get(f"/employees/{employee}/webhook", headers=owner).json()["webhook"] == {
        "url": f"{receiver.base}/result",
        "trigger": "all_connected",
        "secret": MASK,
    }
    publish(api, owner, employee)
    call_event(migrated_url, account, employee)
    tick(migrated_url)
    (sent,) = receiver.seen
    assert verify(SECRET, sent["headers"]["X-Axon-Signature"], sent["body"])


def test_the_test_button_sends_an_example_result_now_and_says_what_came_back(
    api: TestClient, migrated_url: str, receiver: type[Receiver]
) -> None:
    owner, employee, _ = setup(api, migrated_url)
    nothing = api.post(f"/employees/{employee}/webhook/test", headers=owner)
    assert nothing.status_code == 409

    set_hook(api, owner, employee, hook(receiver.base, secret=SECRET))  # a draft: no publish
    receiver.answers = [500]
    result = api.post(f"/employees/{employee}/webhook/test", headers=owner)
    assert result.status_code == 200, result.text
    assert result.json()["response_code"] == 500
    (sent,) = receiver.seen
    assert verify(SECRET, sent["headers"]["X-Axon-Signature"], sent["body"])
    assert receiver.bodies()[0]["test"] is True
    assert SECRET not in result.text
    (record,) = result_sends(migrated_url, employee)
    assert record["is_test"] is True


def test_another_account_cannot_touch_the_hook(api: TestClient, migrated_url: str) -> None:
    owner, employee, _ = setup(api, migrated_url)
    stranger = signup(api, "other@example.com", "Other")
    path = f"/employees/{employee}/webhook"
    assert api.get(path, headers=stranger).status_code == 404
    assert (
        api.put(path, json={"url": "https://a.example.com/h"}, headers=stranger).status_code == 404
    )
    assert api.delete(path, headers=stranger).status_code == 404
    assert api.post(path + "/test", headers=stranger).status_code == 404
    assert api.get(path, headers=owner).status_code == 200
