"""Resend adapter (https://resend.com): transactional email over its REST API.

POST https://api.resend.com/emails with `Authorization: Bearer <key>` and a JSON body of `from`,
`to` (a list), `subject` and `text`; the answer carries the message `id`. The health check lists
the account's domains, which needs a full-access key.
"""

import os

import httpx

from app.providers.base import EmailProvider

BASE = "https://api.resend.com"
TIMEOUT_S = 15.0


class ResendEmail(EmailProvider):
    name = "resend"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=TIMEOUT_S, transport=self._transport)

    async def health(self) -> None:
        async with self._client() as client:
            (await client.get(f"{BASE}/domains", headers=self._headers())).raise_for_status()

    async def send(self, to: str, subject: str, text: str) -> None:
        body = {"from": os.environ["EMAIL_FROM"], "to": [to], "subject": subject, "text": text}
        async with self._client() as client:
            response = await client.post(f"{BASE}/emails", headers=self._headers(), json=body)
            response.raise_for_status()
