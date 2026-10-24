"""Vobiz telephony adapter (REST API v1, https://api.vobiz.ai/api/v1, X-Auth-ID / X-Auth-Token)."""

import os

import httpx

from app.providers.base import TelephonyProvider

BASE_URL = "https://api.vobiz.ai/api/v1"
TIMEOUT_S = 10.0


class VobizTelephony(TelephonyProvider):
    name = "vobiz"

    def __init__(self) -> None:
        self.auth_id = os.environ["VOBIZ_AUTH_ID"]
        self._headers = {"X-Auth-ID": self.auth_id, "X-Auth-Token": os.environ["VOBIZ_AUTH_TOKEN"]}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=f"{BASE_URL}/Account/{self.auth_id}", headers=self._headers, timeout=TIMEOUT_S
        )

    async def health(self) -> None:
        # Cheapest authenticated read: the list of live calls.
        async with self._client() as client:
            (await client.get("/Call", params={"status": "live"})).raise_for_status()

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
