import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app.employees import tickets
from app.providers.telephony.vobiz import BASE_URL, VobizTelephony

from .conftest import TEST_JWT_SECRET, sql
from .helpers import seed, signup

PHONE = "+919876543210"


@pytest.fixture
def api(db_client: TestClient, migrated_url: str, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    seed(migrated_url)
    monkeypatch.setenv("AXON_ENGINE_PUBLIC_URL", "https://engine.example.in")
    return db_client


class Carrier:
    """Vobiz answering `Call fired`; keeps what it was asked."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.status = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": "nope"})
        return httpx.Response(
            200, json={"api_id": "a", "message": "Call fired", "request_uuid": "vz-1"}
        )


@pytest.fixture
def carrier(monkeypatch: pytest.MonkeyPatch) -> Iterator[Carrier]:
    monkeypatch.setenv("VOBIZ_AUTH_ID", "MA_TEST")
    monkeypatch.setenv("VOBIZ_AUTH_TOKEN", "token")
    fake = Carrier()
    transport = httpx.MockTransport(fake.handler)
    monkeypatch.setattr(
        VobizTelephony,
        "_client",
        lambda self: httpx.AsyncClient(
            base_url=f"{BASE_URL}/Account/MA_TEST", headers=self._headers, transport=transport
        ),
    )
    yield fake


def hire(api: TestClient, owner: dict[str, str], url: str, with_number: bool = True) -> str:
    employee = api.post(
        "/employees", json={"channel": "instant", "name": "Asha"}, headers=owner
    ).json()
    if with_number:
        account = sql(url, "SELECT account_id FROM employees WHERE id = :e", {"e": employee["id"]})
        number = sql(
            url,
            "INSERT INTO numbers (account_id, provider, e164, number_type, status)"
            " VALUES (:a, 'vobiz', '+911400000001', 'regular', 'active') RETURNING id",
            {"a": account},
        )
        sql(
            url,
            "UPDATE employees SET number_id = :n WHERE id = :e",
            {"n": number, "e": employee["id"]},
        )
    return str(employee["id"])


def test_a_test_call_rings_the_owner_from_the_employees_number(
    api: TestClient, migrated_url: str, carrier: Carrier
) -> None:
    owner = signup(api)
    employee = hire(api, owner, migrated_url)
    response = api.post(f"/employees/{employee}/test-call", json={"phone": PHONE}, headers=owner)
    assert response.status_code == 202 and response.json()["carrier_call_id"] == "vz-1"
    call_id = response.json()["call_id"]
    body = json.loads(carrier.requests[0].content)
    assert (body["from"], body["to"]) == ("911400000001", "919876543210")
    assert body["answer_url"] == (
        f"https://engine.example.in/vobiz/answer?employee={employee}&call={call_id}"
    )
    row = sql(
        migrated_url,
        "SELECT is_test::text || status::text FROM calls WHERE id = :c",
        {"c": call_id},
    )
    assert row == "truequeued"  # free: flagged as a test, nothing charged


def test_test_call_preconditions(api: TestClient, migrated_url: str, carrier: Carrier) -> None:
    owner = signup(api)
    no_number = hire(api, owner, migrated_url, with_number=False)
    path = f"/employees/{no_number}/test-call"
    assert api.post(path, json={"phone": PHONE}, headers=owner).status_code == 409
    employee = hire(api, owner, migrated_url)
    path = f"/employees/{employee}/test-call"
    for phone in ("9876543210", "+14155550100", "+915876543210", "not a number"):
        assert api.post(path, json={"phone": phone}, headers=owner).status_code == 422, phone
    assert api.post(path, json={"phone": PHONE}).status_code == 401
    assert (
        api.post(path, json={"phone": PHONE}, headers=signup(api, "b@example.com", "B")).status_code
        == 404
    )
    assert carrier.requests == []


def test_test_call_is_503_without_carrier_keys_or_public_url(
    api: TestClient, migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = signup(api)
    path = f"/employees/{hire(api, owner, migrated_url)}/test-call"
    response = api.post(path, json={"phone": PHONE}, headers=owner)
    assert response.status_code == 503 and response.json()["missing_keys"] == [
        "VOBIZ_AUTH_ID",
        "VOBIZ_AUTH_TOKEN",
    ]
    monkeypatch.setenv("VOBIZ_AUTH_ID", "MA_TEST")
    monkeypatch.setenv("VOBIZ_AUTH_TOKEN", "token")
    monkeypatch.delenv("AXON_ENGINE_PUBLIC_URL")
    response = api.post(path, json={"phone": PHONE}, headers=owner)
    assert response.status_code == 503 and response.json()["missing_keys"] == [
        "AXON_ENGINE_PUBLIC_URL"
    ]
    assert sql(migrated_url, "SELECT count(*) FROM calls") == 0


def test_a_carrier_failure_marks_the_call_failed(
    api: TestClient, migrated_url: str, carrier: Carrier
) -> None:
    owner = signup(api)
    path = f"/employees/{hire(api, owner, migrated_url)}/test-call"
    carrier.status = 402
    response = api.post(path, json={"phone": PHONE}, headers=owner)
    assert response.status_code == 502 and response.json()["vendor_status"] == 402
    assert sql(migrated_url, "SELECT status::text FROM calls") == "failed"


def test_test_calls_are_capped_per_account_not_per_employee(
    api: TestClient, migrated_url: str, carrier: Carrier
) -> None:
    owner = signup(api)
    employee = hire(api, owner, migrated_url)
    for _ in range(4):
        assert (
            api.post(
                f"/employees/{employee}/test-call", json={"phone": PHONE}, headers=owner
            ).status_code
            == 202
        )
    for _ in range(6):
        assert api.post(f"/employees/{employee}/web-test-call", headers=owner).status_code == 201
    assert (
        api.post(
            f"/employees/{employee}/test-call", json={"phone": PHONE}, headers=owner
        ).status_code
        == 429
    )
    # Making more employees (free) does not make more free calls.
    for _ in range(3):
        copy = api.post(f"/employees/{employee}/duplicate", headers=owner).json()["id"]
        assert api.post(f"/employees/{copy}/web-test-call", headers=owner).status_code == 429
    # Another account has its own allowance.
    other = signup(api, "b@example.com", "B")
    mine = api.post("/employees", json={"channel": "bulk"}, headers=other).json()["id"]
    assert api.post(f"/employees/{mine}/web-test-call", headers=other).status_code == 201


def test_parallel_requests_cannot_slip_past_the_cap(api: TestClient, migrated_url: str) -> None:
    from concurrent.futures import ThreadPoolExecutor

    owner = signup(api)
    employee = hire(api, owner, migrated_url, with_number=False)

    def ask(_: int) -> int:
        return api.post(f"/employees/{employee}/web-test-call", headers=owner).status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(ask, range(16)))
    assert sorted(codes) == [201] * 10 + [429] * 6
    assert sql(migrated_url, "SELECT count(*) FROM calls WHERE is_test") == 10


def test_web_test_call_hands_out_a_signed_ticket_for_one_employee_and_call(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    employee = hire(api, owner, migrated_url, with_number=False)
    got = api.post(f"/employees/{employee}/web-test-call", headers=owner).json()
    assert got["ws_url"] == f"wss://engine.example.in/web/stream?ticket={got['ticket']}"
    assert got["expires_in"] == 120
    ticket = tickets.read(got["ticket"])
    assert (
        ticket is not None
        and str(ticket.employee_id) == employee
        and str(ticket.call_id) == got["call_id"]
    )
    assert (
        sql(migrated_url, "SELECT is_test FROM calls WHERE id = :c", {"c": got["call_id"]}) is True
    )


def test_tickets_cannot_be_forged_replayed_late_or_swapped_with_login_tokens(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    employee = hire(api, owner, migrated_url, with_number=False)
    ticket = api.post(f"/employees/{employee}/web-test-call", headers=owner).json()["ticket"]
    assert tickets.read(ticket + "x") is None and tickets.read("garbage") is None
    grant = tickets.WebTicket(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    late = tickets.issue(grant, now=datetime.now(UTC) - timedelta(minutes=5))
    assert tickets.read(late) is None
    assert tickets.read(tickets.issue(grant)) == grant
    # A ticket is not a login token, and a login token is not a ticket.
    assert api.get("/accounts/me", headers={"Authorization": f"Bearer {ticket}"}).status_code == 401
    assert tickets.read(owner["Authorization"].removeprefix("Bearer ")) is None
    assert TEST_JWT_SECRET  # same secret signs both; the `typ` claim keeps them apart


def test_web_test_call_is_503_without_a_public_engine_url_and_scoped(
    api: TestClient, migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = signup(api)
    employee = hire(api, owner, migrated_url, with_number=False)
    assert (
        api.post(
            f"/employees/{employee}/web-test-call", headers=signup(api, "b@example.com", "B")
        ).status_code
        == 404
    )
    monkeypatch.delenv("AXON_ENGINE_PUBLIC_URL")
    assert api.post(f"/employees/{employee}/web-test-call", headers=owner).status_code == 503
