"""Top-ups through Razorpay: the order request, both signatures, and one credit per payment."""

import hashlib
import hmac
import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.providers.payments.razorpay import RazorpayPayments

from .conftest import sql
from .helpers import account_id, seed, signup

KEY_ID, SECRET, WEBHOOK_SECRET = "rzp_test_key", "key-secret", "hook-secret"


class Razorpay:
    """Razorpay's orders API: hands out `order_N` and keeps every request it was sent."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        number = len(self.requests)
        return httpx.Response(200, json={"id": f"order_{number}", "status": "created"})


@pytest.fixture
def api(db_client: TestClient, migrated_url: str) -> TestClient:
    seed(migrated_url)
    return db_client


@pytest.fixture
def razorpay(monkeypatch: pytest.MonkeyPatch) -> Iterator[Razorpay]:
    monkeypatch.setenv("RAZORPAY_KEY_ID", KEY_ID)
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", SECRET)
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", WEBHOOK_SECRET)
    fake = Razorpay()
    transport = httpx.MockTransport(fake.handler)
    monkeypatch.setattr(
        RazorpayPayments,
        "_client",
        lambda self: httpx.AsyncClient(
            base_url="https://api.razorpay.com/v1", auth=(KEY_ID, SECRET), transport=transport
        ),
    )
    yield fake


def sign(message: str, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def checkout(order: str, payment: str, signature: str | None = None) -> dict[str, str]:
    return {
        "razorpay_order_id": order,
        "razorpay_payment_id": payment,
        "razorpay_signature": signature or sign(f"{order}|{payment}"),
    }


def event(order: str, payment: str, paise: int, name: str = "payment.captured") -> bytes:
    entity = {"id": payment, "order_id": order, "amount": paise, "status": "captured"}
    return json.dumps({"event": name, "payload": {"payment": {"entity": entity}}}).encode()


def deliver(api: TestClient, body: bytes, signature: str | None = None) -> Any:
    headers = {
        "X-Razorpay-Signature": sign(body.decode(), WEBHOOK_SECRET)
        if signature is None
        else signature
    }
    return api.post("/webhooks/razorpay", content=body, headers=headers)


def order(api: TestClient, owner: dict[str, str], amount: str = "500") -> str:
    response = api.post("/wallet/topup/order", json={"amount_inr": amount}, headers=owner)
    assert response.status_code == 201, response.text
    return str(response.json()["order_id"])


def balance(api: TestClient, owner: dict[str, str]) -> Decimal:
    return Decimal(api.get("/wallet", headers=owner).json()["balance"])


def test_the_order_is_asked_for_in_paise_and_the_secret_stays_server_side(
    api: TestClient, migrated_url: str, razorpay: Razorpay
) -> None:
    owner = signup(api)
    response = api.post("/wallet/topup/order", json={"amount_inr": "500.50"}, headers=owner)
    assert response.status_code == 201
    assert response.json() == {
        "order_id": "order_1",
        "key_id": KEY_ID,
        "amount_paise": 50050,
        "currency": "INR",
    }
    sent = razorpay.requests[0]
    assert (sent.method, str(sent.url)) == ("POST", "https://api.razorpay.com/v1/orders")
    body = json.loads(sent.content)
    assert body["amount"] == 50050 and body["currency"] == "INR"
    assert body["receipt"].startswith("axon_") and len(body["receipt"]) <= 40
    assert SECRET not in response.text
    row = sql(migrated_url, "SELECT status::text || amount_inr::text FROM payments")
    assert row == "created500.50"
    assert balance(api, owner) == 50  # an order is not money yet


def test_amount_limits_and_owner_only(
    api: TestClient, migrated_url: str, razorpay: Razorpay
) -> None:
    owner = signup(api)
    for amount in ("99", "0", "-5", "100001", "abc"):
        got = api.post("/wallet/topup/order", json={"amount_inr": amount}, headers=owner)
        assert got.status_code == 422, amount
    assert api.post("/wallet/topup/order", json={"amount_inr": "100"}).status_code == 401
    member_id = sql(
        migrated_url,
        "INSERT INTO users (account_id, email, password_hash, role)"
        " VALUES (:a, 'm@example.com', 'x', 'member') RETURNING id",
        {"a": account_id(api, owner)},
    )
    from app.auth import issue_token
    from app.models import User

    member = {"Authorization": f"Bearer {issue_token(User(id=member_id))}"}
    assert (
        api.post("/wallet/topup/order", json={"amount_inr": "500"}, headers=member).status_code
        == 403
    )
    assert razorpay.requests == []


def test_every_payment_route_is_503_without_keys(api: TestClient, migrated_url: str) -> None:
    owner = signup(api)
    for response in (
        api.post("/wallet/topup/order", json={"amount_inr": "500"}, headers=owner),
        api.post("/wallet/topup/verify", json=checkout("order_1", "pay_1"), headers=owner),
        api.post("/webhooks/razorpay", content=b"{}", headers={"X-Razorpay-Signature": "x"}),
    ):
        assert response.status_code == 503
        assert response.json()["error"] == "provider_not_configured"
        assert response.json()["missing_keys"] == [
            "RAZORPAY_KEY_ID",
            "RAZORPAY_KEY_SECRET",
            "RAZORPAY_WEBHOOK_SECRET",
        ]
    assert sql(migrated_url, "SELECT count(*) FROM payments") == 0


def test_the_checkout_signature_decides_whether_the_browser_is_believed(
    api: TestClient, migrated_url: str, razorpay: Razorpay
) -> None:
    owner = signup(api)
    order_id = order(api, owner)
    wrong = checkout(order_id, "pay_1", sign("something else"))
    assert api.post("/wallet/topup/verify", json=wrong, headers=owner).status_code == 400
    tampered = checkout(order_id, "pay_2", sign(f"{order_id}|pay_1"))  # signed for another payment
    assert api.post("/wallet/topup/verify", json=tampered, headers=owner).status_code == 400
    forged = checkout(order_id, "pay_1", sign(f"{order_id}|pay_1", "not-the-secret"))
    assert api.post("/wallet/topup/verify", json=forged, headers=owner).status_code == 400
    assert (
        balance(api, owner) == 50
        and sql(migrated_url, "SELECT status::text FROM payments") == "created"
    )
    good = api.post("/wallet/topup/verify", json=checkout(order_id, "pay_1"), headers=owner)
    assert good.status_code == 200 and good.json() == {"status": "paid", "balance": "550.0000"}
    assert sql(migrated_url, "SELECT provider_payment_id FROM payments") == "pay_1"


def test_another_account_cannot_settle_my_order(api: TestClient, razorpay: Razorpay) -> None:
    mine, theirs = signup(api), signup(api, "b@example.com", "B")
    order_id = order(api, mine)
    got = api.post("/wallet/topup/verify", json=checkout(order_id, "pay_1"), headers=theirs)
    assert got.status_code == 404
    assert balance(api, theirs) == 50 and balance(api, mine) == 50


def test_the_webhook_signature_is_checked_on_the_raw_body(
    api: TestClient, razorpay: Razorpay
) -> None:
    owner = signup(api)
    order_id = order(api, owner)
    body = event(order_id, "pay_1", 50000)
    assert deliver(api, body, signature="0" * 64).status_code == 400  # wrong
    assert api.post("/webhooks/razorpay", content=body).status_code == 400  # missing
    tampered = event(order_id, "pay_1", 5000000)  # more money, signature of the real body
    assert deliver(api, tampered, signature=sign(body.decode(), WEBHOOK_SECRET)).status_code == 400
    assert balance(api, owner) == 50
    assert deliver(api, body).status_code == 200
    assert balance(api, owner) == 550


@pytest.mark.parametrize("browser_first", [True, False])
def test_a_payment_credits_once_whichever_reports_first(
    api: TestClient, migrated_url: str, razorpay: Razorpay, browser_first: bool
) -> None:
    owner = signup(api)
    order_id = order(api, owner)

    def browser() -> None:
        got = api.post("/wallet/topup/verify", json=checkout(order_id, "pay_1"), headers=owner)
        assert got.status_code == 200

    def webhook() -> None:
        assert deliver(api, event(order_id, "pay_1", 50000)).status_code == 200

    for report in (browser, webhook) if browser_first else (webhook, browser):
        report()
    webhook()  # and Razorpay retries
    assert balance(api, owner) == 550
    assert sql(migrated_url, "SELECT count(*) FROM wallet_ledger WHERE kind = 'topup'") == 1
    assert sql(migrated_url, "SELECT count(*) FROM invoices") == 1


def test_browser_and_webhook_at_the_same_moment_still_credit_once(
    api: TestClient, migrated_url: str, razorpay: Razorpay
) -> None:
    owner = signup(api)
    order_id = order(api, owner)
    body = event(order_id, "pay_1", 50000)

    def report(index: int) -> int:
        if index % 2:
            return int(deliver(api, body).status_code)
        verify = api.post("/wallet/topup/verify", json=checkout(order_id, "pay_1"), headers=owner)
        return int(verify.status_code)

    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = list(pool.map(report, range(8)))
    assert codes == [200] * 8
    assert balance(api, owner) == 550
    assert sql(migrated_url, "SELECT count(*) FROM wallet_ledger WHERE kind = 'topup'") == 1
    assert sql(migrated_url, "SELECT count(*) FROM invoices") == 1


def test_a_webhook_that_does_not_match_an_order_credits_nothing(
    api: TestClient, migrated_url: str, razorpay: Razorpay
) -> None:
    owner = signup(api)
    order_id = order(api, owner)
    assert deliver(api, event(order_id, "pay_1", 12345)).status_code == 200  # paid another amount
    assert deliver(api, event("order_unknown", "pay_9", 50000)).status_code == 200
    assert deliver(api, event(order_id, "pay_1", 50000, "payment.failed")).status_code == 200
    assert deliver(api, b'{"event": "payment.captured"}').status_code == 400  # unreadable
    assert balance(api, owner) == 50
    assert sql(migrated_url, "SELECT status::text FROM payments") == "created"
