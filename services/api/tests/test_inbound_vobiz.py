"""Routing a number to us: the Vobiz requests as documented, and what going live does."""

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.providers.telephony.vobiz import VobizTelephony

from .conftest import sql
from .dialing import Carrier
from .helpers import live_employee, signup
from .inbound_support import NUMBER, adapter, routed_carrier  # noqa: F401 - the fixture


def sent(requests: list[httpx.Request]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (r.method, r.url.raw_path.decode(), json.loads(r.content) if r.content else {})
        for r in requests
    ]


def test_the_adapter_makes_the_application_attaches_the_number_and_transfers_a_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VOBIZ_AUTH_ID", "MA_TEST")
    monkeypatch.setenv("VOBIZ_AUTH_TOKEN", "token")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/Application/"):
            return httpx.Response(
                201, json={"api_id": "x", "app_id": "app_77", "message": "created"}
            )
        return httpx.Response(202 if "/Call/" in request.url.path else 200, json={})

    vobiz = VobizTelephony(transport=httpx.MockTransport(handler))

    async def work() -> str:
        app = await vobiz.ensure_application(
            "axon-inbound-ab", "https://e/vobiz/inbound", "https://a/vobiz/events"
        )
        await vobiz.route_number("+919100000001", app)
        await vobiz.transfer("call-9", "https://e/vobiz/transfer?ticket=t")
        return app

    import asyncio

    assert asyncio.run(work()) == "app_77"
    base = "/api/v1/Account/MA_TEST"
    assert sent(requests) == [
        (
            "POST",
            f"{base}/Application/",
            {
                "app_name": "axon-inbound-ab",
                "answer_url": "https://e/vobiz/inbound",
                "answer_method": "POST",
                "hangup_url": "https://a/vobiz/events",
                "hangup_method": "POST",
            },
        ),
        ("POST", f"{base}/numbers/%2B919100000001/application", {"application_id": "app_77"}),
        (
            "POST",
            f"{base}/Call/call-9/",
            {
                "legs": "aleg",
                "aleg_url": "https://e/vobiz/transfer?ticket=t",
                "aleg_method": "POST",
            },
        ),
    ]


def make(api: TestClient, url: str, channel: str = "inbound") -> tuple[str, dict[str, str]]:
    owner = signup(api)
    employee = live_employee(api, url, owner, channel=channel, number=NUMBER, live=False)
    return employee, owner


def test_connecting_a_number_makes_one_application_and_attaches_the_number_each_time(
    api: TestClient,
    migrated_url: str,
    routed_carrier: Carrier,  # noqa: F811
) -> None:
    employee, owner = make(api, migrated_url)
    for _ in range(2):
        done = api.post(f"/employees/{employee}/inbound/connect", headers=owner)
        assert done.status_code == 200 and done.json() == {"connected": True, "number": NUMBER}
    (application,) = routed_carrier.applications
    assert application["answer_url"] == "https://engine.example.in/vobiz/inbound"
    assert application["hangup_url"] == "https://api.example.in/vobiz/events"
    assert routed_carrier.routed == {NUMBER: "app_1"}


def test_a_changed_public_address_gets_its_own_application(
    api: TestClient,
    migrated_url: str,
    routed_carrier: Carrier,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    employee, owner = make(api, migrated_url)
    api.post(f"/employees/{employee}/inbound/connect", headers=owner)
    monkeypatch.setenv("AXON_ENGINE_PUBLIC_URL", "https://engine2.example.in")
    api.post(f"/employees/{employee}/inbound/connect", headers=owner)
    assert [a["answer_url"] for a in routed_carrier.applications] == [
        "https://engine.example.in/vobiz/inbound",
        "https://engine2.example.in/vobiz/inbound",
    ]
    assert routed_carrier.routed == {NUMBER: "app_2"}


def test_connect_needs_a_number_and_the_keys(
    api: TestClient, migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    employee, owner = make(api, migrated_url)
    refused = api.post(f"/employees/{employee}/inbound/connect", headers=owner)
    assert refused.status_code == 503 and refused.json()["error"] == "provider_not_configured"
    sql(migrated_url, "UPDATE employees SET number_id = NULL")
    monkeypatch.setenv("VOBIZ_AUTH_ID", "MA_TEST")
    monkeypatch.setenv("VOBIZ_AUTH_TOKEN", "token")
    assert api.post(f"/employees/{employee}/inbound/connect", headers=owner).status_code == 409


def test_an_inbound_employee_goes_live_routed_or_not_at_all(
    api: TestClient, migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    employee, owner = make(api, migrated_url)
    refused = api.post(f"/employees/{employee}/activate", headers=owner)
    assert refused.status_code == 503  # no carrier keys: it could not answer anyone
    assert sql(migrated_url, "SELECT status::text FROM employees") == "training"


def test_an_inbound_employee_goes_live_and_its_number_is_routed(
    api: TestClient,
    migrated_url: str,
    routed_carrier: Carrier,  # noqa: F811
) -> None:
    employee, owner = make(api, migrated_url)
    live = api.post(f"/employees/{employee}/activate", headers=owner)
    assert live.status_code == 200 and live.json()["status"] == "live"
    assert routed_carrier.routed == {NUMBER: "app_1"}


def test_a_carrier_error_while_routing_keeps_an_inbound_employee_from_going_live(
    api: TestClient,
    migrated_url: str,
    routed_carrier: Carrier,  # noqa: F811
) -> None:
    employee, owner = make(api, migrated_url)
    routed_carrier.routing_status = 500
    failed = api.post(f"/employees/{employee}/activate", headers=owner)
    assert failed.status_code == 502 and failed.json()["error"] == "provider_error"
    assert sql(migrated_url, "SELECT status::text FROM employees") == "training"
    routed_carrier.routing_status = 0
    assert api.post(f"/employees/{employee}/activate", headers=owner).status_code == 200


def test_an_outbound_employee_goes_live_without_keys_and_is_routed_when_it_can_be(
    api: TestClient, migrated_url: str, monkeypatch: pytest.MonkeyPatch, no_keys: None
) -> None:
    employee, owner = make(api, migrated_url, channel="instant")
    assert api.post(f"/employees/{employee}/activate", headers=owner).status_code == 200


def test_an_outbound_employee_that_does_not_take_callbacks_is_not_routed(
    api: TestClient,
    migrated_url: str,
    routed_carrier: Carrier,  # noqa: F811
) -> None:
    employee, owner = make(api, migrated_url, channel="instant")
    api.put(
        f"/employees/{employee}/inbound-settings", json={"answer_callbacks": False}, headers=owner
    )
    assert api.post(f"/employees/{employee}/activate", headers=owner).status_code == 200
    assert routed_carrier.routed == {} and routed_carrier.applications == []


def test_an_outbound_employee_is_routed_for_its_callbacks_by_default(
    api: TestClient,
    migrated_url: str,
    routed_carrier: Carrier,  # noqa: F811
) -> None:
    employee, owner = make(api, migrated_url, channel="bulk")
    assert api.post(f"/employees/{employee}/activate", headers=owner).status_code == 200
    assert routed_carrier.routed == {NUMBER: "app_1"}


def test_a_carrier_outage_does_not_keep_an_outbound_employee_from_going_live(
    api: TestClient,
    migrated_url: str,
    routed_carrier: Carrier,  # noqa: F811
) -> None:
    employee, owner = make(api, migrated_url, channel="instant")
    routed_carrier.routing_status = 503
    assert api.post(f"/employees/{employee}/activate", headers=owner).status_code == 200


def test_the_settings_belong_to_the_owners_account_and_the_owner_alone(
    api: TestClient, migrated_url: str
) -> None:
    employee, owner = make(api, migrated_url)
    stranger = signup(api, "other@example.com", "Other")
    path = f"/employees/{employee}/inbound-settings"
    assert api.get(path, headers=stranger).status_code == 404
    assert api.put(path, json={}, headers=stranger).status_code == 404
    saved = api.put(path, json={"closed_message": "Back at nine."}, headers=owner)
    assert (
        saved.status_code == 200
        and api.get(path, headers=owner).json()["closed_message"] == "Back at nine."
    )
    # The transfer number cannot be the line itself.
    own = api.put(path, json={"transfer_number": NUMBER, "transfer_when": "angry"}, headers=owner)
    assert own.status_code == 422 and "own number" in own.json()["detail"]
