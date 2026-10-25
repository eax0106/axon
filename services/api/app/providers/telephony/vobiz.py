"""Vobiz telephony adapter (REST API v1, https://api.vobiz.ai/api/v1, X-Auth-ID / X-Auth-Token)."""

import base64
import hashlib
import hmac
import os
from collections.abc import Mapping

import httpx

from app.providers.base import CallDetail, TelephonyProvider

BASE_URL = "https://api.vobiz.ai/api/v1"
TIMEOUT_S = 10.0


class VobizTelephony(TelephonyProvider):
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

    async def hang_up(self, call_uuid: str) -> None:
        """End a live or queued call. 404 means it already ended, which is fine."""
        async with self._client() as client:
            response = await client.delete(f"/Call/{call_uuid}")
            if response.status_code != 404:
                response.raise_for_status()
