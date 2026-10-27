"""Vobiz number KYC: who a number is registered to (PAN, then Aadhaar through DigiLocker).

Vobiz publishes no reference for its KYC holders (WIRING_CHECKLIST #21), so the paths below are
the ones its console flow implies and must be confirmed against the live API before launch; the
contract test (`requires_keys`) is how. All calls go under /Account/{auth id}/kyc.
"""

import os

import httpx

from app.providers.base import DigilockerStart, NumberKycProvider, PanResult
from app.providers.telephony.vobiz import BASE_URL, TIMEOUT_S


class VobizKyc(NumberKycProvider):
    name = "vobiz"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport
        self.auth_id = os.environ["VOBIZ_AUTH_ID"]
        self._headers = {"X-Auth-ID": self.auth_id, "X-Auth-Token": os.environ["VOBIZ_AUTH_TOKEN"]}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=f"{BASE_URL}/Account/{self.auth_id}/kyc",
            headers=self._headers,
            timeout=TIMEOUT_S,
            transport=self._transport,
        )

    async def health(self) -> None:
        async with self._client() as client:
            (await client.get("/holders")).raise_for_status()

    async def verify_pan(self, pan: str, name: str) -> PanResult:
        async with self._client() as client:
            response = await client.post("/pan", json={"pan": pan, "name": name})
            response.raise_for_status()
            body = response.json()
        return PanResult(
            verified=bool(body.get("verified")),
            name=str(body.get("name") or name),
            holder_ref=str(body.get("holder_id") or ""),
        )

    async def digilocker_start(self, holder_ref: str, redirect_url: str) -> DigilockerStart:
        async with self._client() as client:
            response = await client.post(
                "/digilocker/initiate", json={"holder_id": holder_ref, "redirect_url": redirect_url}
            )
            response.raise_for_status()
            body = response.json()
        return DigilockerStart(url=str(body["url"]), ref=str(body["ref"]))

    async def digilocker_verified(self, holder_ref: str, ref: str) -> bool:
        async with self._client() as client:
            response = await client.post(
                "/digilocker/verify", json={"holder_id": holder_ref, "ref": ref}
            )
            response.raise_for_status()
            return bool(response.json().get("verified"))
