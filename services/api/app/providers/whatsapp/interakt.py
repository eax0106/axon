"""Interakt (WhatsApp BSP): one approved template to one number.

POST https://api.interakt.ai/v1/public/message/ with `Authorization: Basic <API key>`; the number
is split into country code and national digits, `bodyValues` fill {{1}}, {{2}} in order.
"""

import os

import httpx

from app.providers.base import WhatsAppProvider

URL = "https://api.interakt.ai/v1/public/message/"
TIMEOUT_S = 15.0


class InteraktWhatsApp(WhatsAppProvider):
    name = "interakt"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def health(self) -> None:
        # ponytail: Interakt documents no read-only call, so the key is proved by the first send.
        # shortcut: no live probe, upgrade when Interakt documents one.
        if not os.environ.get("INTERAKT_API_KEY"):
            raise RuntimeError("INTERAKT_API_KEY is empty")

    async def send_template(
        self, to_e164: str, name: str, language: str, params: list[str], recipient_name: str
    ) -> None:
        body = {
            "countryCode": "+91",
            "phoneNumber": to_e164.removeprefix("+91"),
            "type": "Template",
            "template": {"name": name, "languageCode": language, "bodyValues": params},
        }
        headers = {"Authorization": f"Basic {os.environ['INTERAKT_API_KEY']}"}
        async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=self._transport) as client:
            response = await client.post(URL, json=body, headers=headers)
        if response.status_code >= 400 or response.json().get("result") is not True:
            raise RuntimeError(f"Interakt refused the message ({response.status_code})")
