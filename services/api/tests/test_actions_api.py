import json
from typing import Any

from fastapi.testclient import TestClient

from app.actions.schema import MASK
from app.providers.google import calendar as g_calendar

from .actions_support import (
    ALL_SCOPES,
    PHONE,
    WHATSAPP_ACTION,
    Google,
    Shop,
    Vendor,
    calendar_action,
    connect_google,
    http_action,
    put_actions,
    sheet_write,
)
from .conftest import sql
from .helpers import account_id, add_member, signup

MASKED = {"kind": "bearer", "secret": MASK}
SECRET = "tok-very-secret-123"  # noqa: S105 - a test value


def new_employee(client: TestClient, owner: dict[str, str]) -> str:
    return str(client.post("/employees", json={"channel": "inbound"}, headers=owner).json()["id"])


def secret_http(**changes: Any) -> dict[str, Any]:
    return http_action(auth={"kind": "bearer", "secret": SECRET}, **changes)


def test_actions_are_draft_edits_until_publish_and_travel_with_versions(api: TestClient) -> None:
    owner = signup(api)
    employee = new_employee(api, owner)
    api.post(f"/employees/{employee}/publish", headers=owner)
    saved = put_actions(api, owner, employee, http_action())
    assert saved.status_code == 200 and saved.json()["actions"][0]["name"] == "order_status"
    shown = api.get(f"/employees/{employee}", headers=owner).json()
    assert shown["has_pending_edits"] is True and shown["published_version"] == 1
    assert (
        api.get(f"/employees/{employee}/versions", headers=owner).json()[0]["script"]["actions"]
        == []
    )
    assert (
        api.post(f"/employees/{employee}/publish", headers=owner).json()["has_pending_edits"]
        is False
    )
    assert (
        len(
            api.get(f"/employees/{employee}/versions", headers=owner).json()[0]["script"]["actions"]
        )
        == 1
    )
    put_actions(api, owner, employee)  # remove them again
    assert api.get(f"/employees/{employee}/actions", headers=owner).json() == {"actions": []}
    api.post(f"/employees/{employee}/revert", headers=owner)  # back to the published version
    assert len(api.get(f"/employees/{employee}/actions", headers=owner).json()["actions"]) == 1
    put_actions(api, owner, employee)
    api.post(f"/employees/{employee}/publish", headers=owner)
    api.post(f"/employees/{employee}/versions/2/restore", headers=owner)
    assert len(api.get(f"/employees/{employee}/actions", headers=owner).json()["actions"]) == 1


def test_a_secret_never_leaves_the_server_and_a_masked_edit_keeps_it(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    employee = new_employee(api, owner)
    responses = [
        put_actions(api, owner, employee, secret_http()),
        api.get(f"/employees/{employee}/actions", headers=owner),
        api.get(f"/employees/{employee}", headers=owner),
        api.post(f"/employees/{employee}/publish", headers=owner),
        api.get(f"/employees/{employee}/versions", headers=owner),
        api.get(f"/employees/{employee}/prompt", headers=owner),
        api.get("/employees", headers=owner),
    ]
    assert all(r.status_code == 200 for r in responses)
    assert all(SECRET not in r.text for r in responses)
    assert MASK in responses[0].text
    # Sending the masked copy back (a form that was loaded and saved) keeps the real secret.
    shown = api.get(f"/employees/{employee}", headers=owner).json()["script"]
    assert api.put(f"/employees/{employee}/script", json=shown, headers=owner).status_code == 200
    stored = "SELECT draft->'actions'->0->'auth'->>'secret' FROM employees WHERE id = :e"
    assert sql(migrated_url, stored, {"e": employee}) == SECRET
    assert put_actions(api, owner, employee, secret_http(description="Changed.")).status_code == 200
    assert sql(migrated_url, stored, {"e": employee}) == SECRET
    # A masked secret for an action that never had one is refused, not saved as a password.
    unseen = http_action(name="other", auth={"kind": "bearer", "secret": MASK})
    refused = put_actions(api, owner, employee, unseen)
    assert refused.status_code == 422 and "send the secret" in refused.text
    changed = secret_http()
    changed["auth"]["secret"] = "brand-new"  # noqa: S105
    put_actions(api, owner, employee, changed)
    assert sql(migrated_url, stored, {"e": employee}) == "brand-new"


def test_a_script_sent_without_actions_leaves_them_and_an_empty_list_clears_them(
    api: TestClient,
) -> None:
    owner = signup(api)
    employee = new_employee(api, owner)
    put_actions(api, owner, employee, http_action())
    script = {"welcome_message": "Hello"}
    assert api.put(f"/employees/{employee}/script", json=script, headers=owner).status_code == 200
    assert len(api.get(f"/employees/{employee}/actions", headers=owner).json()["actions"]) == 1
    cleared = {"welcome_message": "Hello", "actions": []}
    api.put(f"/employees/{employee}/script", json=cleared, headers=owner)
    assert api.get(f"/employees/{employee}/actions", headers=owner).json() == {"actions": []}


def test_bad_lists_are_refused_with_the_reason(api: TestClient) -> None:
    owner = signup(api)
    employee = new_employee(api, owner)
    twice = put_actions(api, owner, employee, http_action(), http_action())
    assert twice.status_code == 422 and "own name" in twice.text
    assert put_actions(api, owner, employee, http_action(name="end_call")).status_code == 422
    unknown = put_actions(api, owner, employee, {"kind": "sms", "name": "x", "description": "d"})
    assert unknown.status_code == 422
    many = [http_action(name=f"a{i}") for i in range(11)]
    assert put_actions(api, owner, employee, *many).status_code == 422
    assert api.get(f"/employees/{employee}/actions", headers=owner).json() == {"actions": []}


def test_google_backed_actions_need_the_account_to_have_connected_google(
    actions_api: tuple[TestClient, Google],
) -> None:
    client, google = actions_api
    owner = signup(client)
    employee = new_employee(client, owner)
    refused = put_actions(client, owner, employee, calendar_action())
    assert refused.status_code == 409 and "connect Google calendar first" in refused.text
    script = {"actions": [sheet_write()]}
    assert (
        client.put(f"/employees/{employee}/script", json=script, headers=owner).status_code == 409
    )
    google.granted = " ".join(g_calendar.SCOPES)  # the owner allowed Calendar only
    connect_google(client, owner, ("calendar",))
    assert put_actions(client, owner, employee, calendar_action()).status_code == 200
    assert put_actions(client, owner, employee, sheet_write()).status_code == 409  # not Sheets
    google.granted = ALL_SCOPES
    connect_google(client, owner)
    assert put_actions(client, owner, employee, calendar_action(), sheet_write()).status_code == 200
    # Disconnecting later does not delete the actions; it tells the owner they will not work.
    client.delete("/integrations/google", headers=owner)
    warnings = client.get(f"/employees/{employee}", headers=owner).json()["warnings"]
    assert "your actions need Google calendar connected" in warnings
    assert "your actions need Google sheets connected" in warnings


def test_another_account_cannot_read_edit_or_test_my_actions(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    other = signup(api, "other@example.com", "Other")
    employee = new_employee(api, owner)
    put_actions(api, owner, employee, http_action())
    for response in (
        api.get(f"/employees/{employee}/actions", headers=other),
        put_actions(api, other, employee),
        api.post(f"/employees/{employee}/actions/order_status/test", json={}, headers=other),
    ):
        assert response.status_code == 404
    member = add_member(api, migrated_url, owner)
    assert (
        put_actions(api, member, employee, http_action(description="A teammate edit.")).status_code
        == 200
    )


def test_the_test_console_runs_the_real_http_call_and_is_rate_limited(
    api: TestClient, shop: str
) -> None:
    owner = signup(api)
    employee = new_employee(api, owner)
    put_actions(api, owner, employee, http_action(url=shop + "/orders/{order_id}"))
    url = f"/employees/{employee}/actions/order_status/test"
    result = api.post(url, json={"args": {"order_id": "7"}}, headers=owner).json()
    assert result["ok"] is True and json.loads(result["result"]["result"])["path"] == "/orders/7"
    assert Shop.seen[-1]["path"] == "/orders/7"
    missing = api.post(url, json={"args": {}}, headers=owner).json()
    assert missing == {"ok": False, "result": {"ok": False, "error": "order_id is needed"}}
    assert (
        api.post(f"/employees/{employee}/actions/nope/test", json={}, headers=owner).status_code
        == 404
    )
    codes = [
        api.post(url, json={"args": {"order_id": "1"}}, headers=owner).status_code
        for _ in range(30)
    ]
    assert codes[-1] == 429 and codes.count(200) == 28  # 2 used above, 30 an hour


def test_the_test_console_for_a_calendar_books_the_first_free_time_and_removes_it(
    actions_api: tuple[TestClient, Google],
) -> None:
    client, google = actions_api
    owner = signup(client)
    connect_google(client, owner)
    employee = new_employee(client, owner)
    put_actions(client, owner, employee, calendar_action())
    result = client.post(f"/employees/{employee}/actions/visit/test", json={}, headers=owner).json()
    assert result["ok"] is True and result["result"]["booked"]
    assert len(google.deleted) == 1 and google.events == {}


def test_the_test_console_writes_a_sheet_row_and_reads_one(
    actions_api: tuple[TestClient, Google],
) -> None:
    client, google = actions_api
    owner = signup(client)
    connect_google(client, owner)
    employee = new_employee(client, owner)
    read = {"kind": "sheet_read", "name": "find", "description": "d", "sheet_id": "sheet-1"}
    put_actions(client, owner, employee, sheet_write(), read)
    base = f"/employees/{employee}/actions"
    wrote = client.post(f"{base}/save_lead/test", json={"args": {"name": "Asha"}}, headers=owner)
    assert wrote.json()["ok"] is True and google.appended[0]["values"][0][2] == "Asha"
    found = client.post(f"{base}/find/test", json={"args": {"lookup": "gold"}}, headers=owner)
    assert found.json()["result"]["rows"] == [["Asha", "Gold"]]
    client.delete("/integrations/google", headers=owner)
    assert client.post(f"{base}/find/test", json={}, headers=owner).status_code == 409


def test_the_test_message_goes_only_to_the_owners_verified_phone(
    interakt: Vendor, api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    employee = new_employee(api, owner)
    put_actions(api, owner, employee, WHATSAPP_ACTION)
    url = f"/employees/{employee}/actions/send_price/test"
    args = {"args": {"plan": "Gold", "phone": "+919000000000"}}
    refused = api.post(url, json=args, headers=owner)
    assert refused.status_code == 409 and "verify your own phone" in refused.text
    sql(
        migrated_url,
        "UPDATE accounts SET owner_phone = :p, owner_phone_verified_at = now() WHERE id = :a",
        {"p": PHONE, "a": account_id(api, owner)},
    )
    sent = api.post(url, json=args, headers=owner).json()
    assert sent["ok"] is True
    assert [b["phoneNumber"] for b in interakt.sent()] == ["9876543210"]


def test_a_vendor_that_refuses_the_test_is_a_502_with_no_secret_in_it(
    interakt: Vendor, api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    employee = new_employee(api, owner)
    put_actions(api, owner, employee, WHATSAPP_ACTION)
    sql(
        migrated_url,
        "UPDATE accounts SET owner_phone = :p, owner_phone_verified_at = now() WHERE id = :a",
        {"p": PHONE, "a": account_id(api, owner)},
    )
    interakt.status = 400
    response = api.post(
        f"/employees/{employee}/actions/send_price/test",
        json={"args": {"plan": "G"}},
        headers=owner,
    )
    assert response.status_code in (500, 502)


def test_a_masked_secret_does_not_follow_the_action_to_another_host(
    api: TestClient, shop: str, migrated_url: str
) -> None:
    owner = signup(api)
    employee = new_employee(api, owner)
    assert put_actions(api, owner, employee, secret_http()).status_code == 200
    member = add_member(api, migrated_url, owner)
    moved = http_action(url="https://attacker.example.in/{order_id}", auth=MASKED)
    refused = put_actions(api, member, employee, moved)
    assert refused.status_code == 422 and "host changed" in refused.json()["detail"]
    # The same host, another path: the secret stays with the action.
    same_host = secret_http(url=shop + "/other/{order_id}")
    assert put_actions(api, owner, employee, same_host).status_code == 200
    again = http_action(url=shop + "/third/{order_id}", auth=MASKED)
    assert put_actions(api, member, employee, again).status_code == 200
    api.post(
        f"/employees/{employee}/actions/order_status/test",
        json={"args": {"order_id": "1"}},
        headers=member,
    )
    assert Shop.seen[-1]["headers"]["Authorization"] == f"Bearer {SECRET}"


def test_only_the_owner_can_change_which_spreadsheet_an_action_uses(
    actions_api: tuple[TestClient, Google], migrated_url: str
) -> None:
    client, _google = actions_api
    owner = signup(client)
    connect_google(client, owner)
    employee = new_employee(client, owner)
    member = add_member(client, migrated_url, owner)
    refused = put_actions(client, member, employee, sheet_write())
    assert refused.status_code == 403 and "owner" in refused.json()["detail"]
    assert put_actions(client, owner, employee, sheet_write()).status_code == 200
    # A member can still edit the other actions and leave the sheet action as it is.
    kept = put_actions(client, member, employee, sheet_write(), http_action())
    assert kept.status_code == 200
    dropped = put_actions(client, member, employee, http_action())
    assert dropped.status_code == 403
