"""Vobiz telephony adapter (REST API v1, https://api.vobiz.ai/api/v1, X-Auth-ID / X-Auth-Token)."""

import base64
import hashlib
import hmac
import os
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import httpx

from app.providers.base import CallDetail, InventoryNumber, NumberStore, TelephonyProvider

BASE_URL = "https://api.vobiz.ai/api/v1"
TIMEOUT_S = 10.0


class VobizTelephony(TelephonyProvider, NumberStore):
    name = "vobiz"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport
        self.auth_id = os.environ["VOBIZ_AUTH_ID"]
        self._headers = {"X-Auth-ID": self.auth_id, "X-Auth-Token": os.environ["VOBIZ_AUTH_TOKEN"]}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=f"{BASE_URL}/Account/{self.auth_id}",
            headers=self._headers,
            timeout=TIMEOUT_S,
            transport=self._transport,
        )

    async def health(self) -> None:
        # Cheapest authenticated read: the list of live calls.
        async with self._client() as client:
            (await client.get("/Call", params={"status": "live"})).raise_for_status()

    async def originate(
        self, from_number: str, to_number: str, answer_url: str, hangup_url: str | None = None
    ) -> str:
        # The trailing slash is required: without it Vobiz answers 401.
        body = {
            "from": from_number.lstrip("+"),
            "to": to_number.lstrip("+"),
            "answer_url": answer_url,
            "answer_method": "POST",
        }
        if hangup_url:
            body |= {"hangup_url": hangup_url, "hangup_method": "POST"}
        async with self._client() as client:
            response = await client.post("/Call/", json=body)
            response.raise_for_status()
            return str(response.json()["request_uuid"])

    def callback_is_authentic(self, url: str, headers: Mapping[str, str]) -> bool:
        """Vobiz signs the callback URL (query string removed) and a nonce, not the body:
        X-Vobiz-Signature-V3 = base64(HMAC-SHA256(auth token, f"{url}.{nonce}")). Fails closed
        when the headers are missing."""
        lowered = {k.lower(): v for k, v in headers.items()}
        signature = lowered.get("x-vobiz-signature-v3")
        nonce = lowered.get("x-vobiz-signature-v3-nonce")
        if not signature or not nonce:
            return False
        token = os.environ["VOBIZ_AUTH_TOKEN"].encode()
        digest = hmac.new(token, f"{url}.{nonce}".encode(), hashlib.sha256).digest()
        return hmac.compare_digest(base64.b64encode(digest).decode(), signature)

    async def call_detail(self, call_uuid: str) -> CallDetail | None:
        """The call detail record. Vobiz counts a call as answered when talk time (`billsec`) is
        above zero; the hangup callback itself says `completed` for every ending."""
        async with self._client() as client:
            response = await client.get(f"/cdr/{call_uuid}")
            if response.status_code == 404:
                return None  # not written yet
            response.raise_for_status()
            record = response.json()
        talk = int(record.get("billsec") or 0)
        return CallDetail(
            answered=talk > 0,
            duration_s=int(record.get("duration") or 0),
            talk_s=talk,
            hangup_cause=str(record.get("hangup_cause") or "UNKNOWN"),
        )

    async def is_live(self, call_uuid: str) -> bool:
        async with self._client() as client:
            response = await client.get(f"/Call/{call_uuid}", params={"status": "live"})
            if response.status_code == 404:
                return False
            response.raise_for_status()
            return True

    async def live_parties(self, call_uuid: str) -> tuple[str, str] | None:
        """From the live-call record (docs: /call/retrieve-live-call), not from a request."""
        async with self._client() as client:
            response = await client.get(f"/Call/{call_uuid}", params={"status": "live"})
            if response.status_code == 404:
                return None
            response.raise_for_status()
            record = response.json()
            return str(record.get("from") or ""), str(record.get("to") or "")

    async def hang_up(self, call_uuid: str) -> None:
        """End a live or queued call. 404 means it already ended, which is fine."""
        async with self._client() as client:
            response = await client.delete(f"/Call/{call_uuid}")
            if response.status_code != 404:
                response.raise_for_status()

    async def ensure_application(self, name: str, answer_url: str, hangup_url: str) -> str:
        """A voice application: Vobiz fetches its answer URL for every call on a number attached to
        it, and tells its hangup URL when the call ends (docs: /applications/create-application)."""
        body = {
            "app_name": name,
            "answer_url": answer_url,
            "answer_method": "POST",
            "hangup_url": hangup_url,
            "hangup_method": "POST",
        }
        async with self._client() as client:
            response = await client.post("/Application/", json=body)
            response.raise_for_status()
            return str(response.json()["app_id"])

    async def route_number(self, e164: str, application_id: str) -> None:
        """Attach the number to the application; attaching again overwrites (docs:
        /applications/attach-number)."""
        async with self._client() as client:
            response = await client.post(
                f"/numbers/{e164.replace('+', '%2B')}/application",
                json={"application_id": application_id},
            )
            response.raise_for_status()

    async def transfer(self, call_uuid: str, instructions_url: str) -> None:
        """Run new instructions on the caller's leg of a live call: 202 when accepted, 404 if the
        call is not in progress (docs: /call/transfer-call)."""
        body = {"legs": "aleg", "aleg_url": instructions_url, "aleg_method": "POST"}
        async with self._client() as client:
            (await client.post(f"/Call/{call_uuid}/", json=body)).raise_for_status()

    # --- Number store (docs: https://www.skills.sh/vobiz-ai/agent-skills/vobiz-phone-numbers) ----
    # Inventory: GET /inventory/numbers?country&search&page&per_page (max 100). Buying debits the
    # carrier balance by setup + monthly fee: POST /numbers/purchase-from-inventory. Releasing is
    # permanent and the number returns to stock: DELETE /numbers/{e164}, "+" sent as %2B. The
    # docs do not show response bodies, so the reader accepts the usual shapes.

    async def search_numbers(
        self, search: str = "", page: int = 1, per_page: int = 20
    ) -> list[InventoryNumber]:
        params: dict[str, str | int] = {
            "country": "IN",
            "search": search,
            "page": page,
            "per_page": min(per_page, 100),
        }
        async with self._client() as client:
            response = await client.get("/inventory/numbers", params=params)
            response.raise_for_status()
            body = response.json()
        rows: list[dict[str, Any]] = body if isinstance(body, list) else (
            body.get("items") or body.get("numbers") or []
        )  # fmt: skip
        return [_inventory_number(row) for row in rows if row.get("e164") or row.get("number")]

    async def buy_number(self, e164: str) -> str:
        async with self._client() as client:
            response = await client.post(
                "/numbers/purchase-from-inventory", json={"e164": e164, "currency": "INR"}
            )
            response.raise_for_status()
            body = response.json() if response.content else {}
        return str(body.get("id") or body.get("e164") or e164)

    async def release_number(self, e164: str) -> None:
        async with self._client() as client:
            response = await client.delete(f"/numbers/{e164.replace('+', '%2B')}")
            if response.status_code != 404:
                response.raise_for_status()


def _inventory_number(row: dict[str, Any]) -> InventoryNumber:
    e164 = str(row.get("e164") or row.get("number"))
    return InventoryNumber(
        e164=e164,
        number_type=number_type_of(e164),
        setup_fee=Decimal(str(row.get("setup_fee") or 0)),
        monthly_fee=Decimal(str(row.get("monthly_fee") or 0)),
    )


def number_type_of(e164: str) -> str:
    """Regular, 140 or 1600 from the digits: +91 140… is the promotional series and +91 1600… the
    service one."""
    national = e164.removeprefix("+91")
    if national.startswith("1600"):
        return "1600"
    if national.startswith("140"):
        return "140"
    return "regular"
