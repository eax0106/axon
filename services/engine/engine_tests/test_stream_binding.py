"""Vobiz's URLs are public: the answer URLs need the carrier's signature, and the media stream is
served only to the call its row was made for (security test 26 Nov, M2)."""

import json
import os
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from tests.conftest import sql
from tests.helpers import add_call, add_lead, live_employee
from tests.inbound_support import calls, inbound_employee

import engine.main
from app.settings import get_settings
from engine.main import app

from .test_call import _Carrier, events, providers, signed  # noqa: F401 - fixtures
from .test_inbound_engine import form
from .test_vobiz import START

CARRIER_CALL = START["start"]["callId"]


def test_the_answer_urls_refuse_a_request_vobiz_did_not_sign(
    api: TestClient,
    migrated_url: str,
    providers: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    employee, _owner = inbound_employee(api, migrated_url)
    set_up: list[Any] = []
    monkeypatch.setattr(engine.main, "_setup", lambda *a: set_up.append(a))
    with TestClient(app) as client:
        inbound = client.post("/vobiz/inbound", data=form())
        answer = client.post(f"/vobiz/answer?employee={employee}&call={uuid.uuid4()}")
    assert inbound.status_code == answer.status_code == 401
    assert calls(migrated_url) == [] and set_up == []  # refused before any database work


def test_a_signed_request_cannot_be_replayed(
    api: TestClient,
    migrated_url: str,
    providers: None,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_url = os.environ.get("AXON_TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("AXON_TEST_REDIS_URL not set; nonces are remembered in Redis")
    monkeypatch.setenv("REDIS_URL", redis_url)
    get_settings.cache_clear()
    inbound_employee(api, migrated_url)
    headers = signed()
    with TestClient(app) as client:
        first = client.post("/vobiz/inbound", headers=headers, data=form())
        again = client.post("/vobiz/inbound", headers=headers, data=form())
    assert first.status_code == 200 and again.status_code == 409
    assert len(calls(migrated_url)) == 1


def _outbound_call(url: str, employee: str, request_id: str = "req-1") -> Any:
    """A dialed call as the dialer leaves it: the carrier knows it by its dial-request id."""
    account = sql(url, "SELECT account_id FROM employees WHERE id = :e", {"e": employee})
    lead = add_lead(url, account, f"+9198765{uuid.uuid4().int % 100000:05d}", "Ravi")
    call = add_call(url, account, employee, lead, status="ringing", direction="outbound")
    sql(url, "UPDATE calls SET carrier_call_id = :r WHERE id = :c", {"r": request_id, "c": call})
    return call


def _stream(client: TestClient, call: Any, employee: Any) -> int:
    """Open the stream as Vobiz would for `CARRIER_CALL`; the close code it is refused with."""
    with client.websocket_connect(f"/vobiz/stream?lang=en&call={call}&employee={employee}") as ws:
        ws.send_text(json.dumps(START))
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
    return closed.value.code


def test_the_answer_ties_the_carriers_call_to_our_row(
    api: TestClient,
    migrated_url: str,
    providers: None,  # noqa: F811
) -> None:
    employee, _owner = inbound_employee(api, migrated_url)
    call = _outbound_call(migrated_url, employee)
    query = f"employee={employee}&call={call}"
    with TestClient(app) as client:
        answered = client.post(
            f"/vobiz/answer?{query}", headers=signed(), data={"CallUUID": CARRIER_CALL}
        )
    assert answered.status_code == 200
    leg = sql(migrated_url, "SELECT carrier_leg_id FROM calls WHERE id = :c", {"c": call})
    assert leg == CARRIER_CALL
    with TestClient(app) as client:  # a later answer naming another call does not move it
        client.post(f"/vobiz/answer?{query}", headers=signed(), data={"CallUUID": "other"})
    assert sql(migrated_url, "SELECT carrier_leg_id FROM calls WHERE id = :c", {"c": call}) == leg


def test_a_stream_is_refused_unless_its_row_waits_for_this_call_and_employee(
    api: TestClient,
    migrated_url: str,
    providers: None,  # noqa: F811
    events: list[dict[str, Any]],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    employee, owner = inbound_employee(api, migrated_url)
    other_employee = live_employee(api, migrated_url, owner, number="+919100000002")
    not_ours = _outbound_call(migrated_url, employee)  # waits for req-1, not CARRIER_CALL
    ours = _outbound_call(migrated_url, employee, request_id=CARRIER_CALL)
    asked: list[str] = []

    async def is_live(_self: Any, call_uuid: str) -> bool:
        asked.append(call_uuid)
        return True

    monkeypatch.setattr(_Carrier, "is_live", is_live)
    with TestClient(app) as client:
        refused = [
            _stream(client, not_ours, employee),  # another carrier call's row
            _stream(client, ours, other_employee),  # the right call, someone else's employee
            _stream(client, uuid.uuid4(), employee),  # no such row
            _stream(client, "", ""),  # no row named at all
        ]
    assert refused == [1008] * 4
    assert asked == [] and events == []  # nothing was asked of the carrier, nothing was run
    statuses = sql(migrated_url, "SELECT array_agg(status::text) FROM calls")
    assert statuses == ["ringing", "ringing"]
