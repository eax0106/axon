"""Razorpay adapter (https://razorpay.com/docs/api/orders/): card and UPI top-ups.

An order is `POST https://api.razorpay.com/v1/orders` with HTTP basic auth (key id, key secret)
and a JSON body of `amount` (paise), `currency` and `receipt`. The browser's checkout then returns
`razorpay_order_id`, `razorpay_payment_id` and `razorpay_signature`, where the signature is
hex HMAC-SHA256 of "<order id>|<payment id>" under the key secret. Webhooks carry the hex
HMAC-SHA256 of the raw body under the webhook secret in `X-Razorpay-Signature`.
"""

import hashlib
import hmac
import os
from collections.abc import Mapping

import httpx

from app.providers.base import Order, PaymentProvider

BASE = "https://api.razorpay.com/v1"
TIMEOUT_S = 15.0


def _hex_hmac(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


class RazorpayPayments(PaymentProvider):
    name = "razorpay"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport
        self._key_id = os.environ["RAZORPAY_KEY_ID"]
        self._secret = os.environ["RAZORPAY_KEY_SECRET"]
        self._webhook_secret = os.environ["RAZORPAY_WEBHOOK_SECRET"]

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=BASE,
            auth=(self._key_id, self._secret),
            timeout=TIMEOUT_S,
            transport=self._transport,
        )

    async def health(self) -> None:
        async with self._client() as client:
            (await client.get("/orders", params={"count": 1})).raise_for_status()

    async def create_order(self, amount_paise: int, receipt: str) -> Order:
        body = {"amount": amount_paise, "currency": "INR", "receipt": receipt}
        async with self._client() as client:
            response = await client.post("/orders", json=body)
            response.raise_for_status()
            return Order(id=str(response.json()["id"]))

    def public_key(self) -> str:
        return self._key_id

    def checkout_is_authentic(self, order_id: str, payment_id: str, signature: str) -> bool:
        expected = _hex_hmac(self._secret, f"{order_id}|{payment_id}".encode())
        return hmac.compare_digest(expected, signature)

    def webhook_is_authentic(self, body: bytes, headers: Mapping[str, str]) -> bool:
        signature = {k.lower(): v for k, v in headers.items()}.get("x-razorpay-signature")
        if not signature:
            return False
        return hmac.compare_digest(_hex_hmac(self._webhook_secret, body), signature)
