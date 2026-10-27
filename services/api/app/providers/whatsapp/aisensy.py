"""AiSensy (WhatsApp BSP): one live API campaign (it holds the approved template) to one number.

POST https://backend.aisensy.com/campaign/t1/api with the API key in the body; `templateParams`
fill the template's placeholders in order and must match their number.
"""

import os

import httpx

from app.providers.base import WhatsAppProvider

URL = "https://backend.aisensy.com/campaign/t1/api"
TIMEOUT_S = 15.0


class AiSensyWhatsApp(WhatsAppProvider):
    name = "aisensy"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def health(self) -> None:
        # ponytail: AiSensy documents no read-only call, so the key is proved by the first send.
        # shortcut: no live probe, upgrade when AiSensy documents one.
        if not os.environ.get("AISENSY_API_KEY"):
            raise RuntimeError("AISENSY_API_KEY is empty")

    async def send_template(
        self, to_e164: str, name: str, language: str, params: list[str], recipient_name: str
    ) -> None:
        # The language is part of the campaign's template at AiSensy, so `language` is not sent.
        body = {
            "apiKey": os.environ["AISENSY_API_KEY"],
            "campaignName": name,
            "destination": to_e164,
            "userName": recipient_name or "Customer",
            "source": "Axon call",
            "templateParams": params,
        }
        async with httpx.AsyncClient(timeout=TIMEOUT_S, transport=self._transport) as client:
            response = await client.post(URL, json=body)
        if response.status_code >= 400:
            raise RuntimeError(f"AiSensy refused the message ({response.status_code})")
