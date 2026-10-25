"""Meta Lead Ads: the webhook handshake and signature, and fetching a lead from the Graph API.

Webhook (docs: graph-api/webhooks/getting-started and .../webhooks-for-leadgen): Meta verifies
our URL with a GET (`hub.mode`, `hub.verify_token`, `hub.challenge`) and then POSTs `leadgen`
changes signed with `X-Hub-Signature-256: sha256=<HMAC-SHA256 of the raw body, app secret>`.
The webhook carries only ids; the lead's answers are fetched with the page's access token.
"""

import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import Any

import httpx

from app.providers.base import LeadSourceProvider

GRAPH = "https://graph.facebook.com/v26.0"
TIMEOUT_S = 15.0


@dataclass(frozen=True)
class LeadgenEvent:
    leadgen_id: str
    form_id: str


class MetaLeadAds(LeadSourceProvider):
    name = "meta_lead_ads"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=TIMEOUT_S, transport=self._transport)

    async def health(self) -> None:
        # The app's own token (id|secret) can read the app itself: proves the id and secret pair.
        token = f"{os.environ['META_APP_ID']}|{os.environ['META_APP_SECRET']}"
        async with self._client() as client:
            (await client.get(f"{GRAPH}/app", params={"access_token": token})).raise_for_status()

    def challenge(self, mode: str, verify_token: str, challenge: str) -> str | None:
        """The text to answer Meta's verification GET with, or None if it is not ours."""
        expected = os.environ["META_VERIFY_TOKEN"]
        if mode == "subscribe" and hmac.compare_digest(verify_token, expected):
            return challenge
        return None

    def valid_signature(self, body: bytes, header: str | None) -> bool:
        if not header or not header.startswith("sha256="):
            return False
        secret = os.environ["META_APP_SECRET"].encode()
        digest = hmac.new(secret, body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(header.removeprefix("sha256="), digest)

    def events(self, payload: dict[str, Any]) -> list[LeadgenEvent]:
        found = []
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                if change.get("field") == "leadgen" and value.get("leadgen_id"):
                    found.append(
                        LeadgenEvent(str(value["leadgen_id"]), str(value.get("form_id", "")))
                    )
        return found

    async def fetch_lead(self, leadgen_id: str, page_token: str) -> dict[str, str]:
        """The lead's form answers as {field name: first value}."""
        async with self._client() as client:
            response = await client.get(
                f"{GRAPH}/{leadgen_id}", params={"access_token": page_token}
            )
            response.raise_for_status()
            data = response.json()
        return {f["name"]: (f.get("values") or [""])[0] for f in data.get("field_data", [])}
