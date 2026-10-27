"""Google Calendar for in-call booking: free/busy lookups and events.

freeBusy is POST https://www.googleapis.com/calendar/v3/freeBusy; events are created with
POST .../calendars/{id}/events (a caller-chosen event id makes a repeat a 409) and removed with
DELETE .../calendars/{id}/events/{eventId}. One OAuth consent covers Calendar and Sheets.
"""

from datetime import datetime
from urllib.parse import quote

import httpx

from app.providers.base import Busy, CalendarProvider, OAuthGrant
from app.providers.google import oauth

API = "https://www.googleapis.com/calendar/v3"
SCOPES = (
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.freebusy",
)
IST = "Asia/Kolkata"


class GoogleCalendar(CalendarProvider):
    name = "google"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=oauth.TIMEOUT_S, transport=self._transport)

    async def health(self) -> None:
        async with self._client() as client:
            await oauth.check_client(client)

    async def exchange_code(self, code: str, redirect_uri: str) -> OAuthGrant:
        async with self._client() as client:
            return await oauth.exchange(client, code, redirect_uri)

    async def revoke(self, refresh_token: str) -> None:
        async with self._client() as client:
            await oauth.revoke(client, refresh_token)

    async def _headers(self, client: httpx.AsyncClient, refresh_token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {await oauth.access_token(client, refresh_token)}"}

    async def busy(
        self, refresh_token: str, calendar_id: str, start: datetime, end: datetime
    ) -> list[Busy]:
        body = {
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "timeZone": IST,
            "items": [{"id": calendar_id}],
        }
        async with self._client() as client:
            headers = await self._headers(client, refresh_token)
            response = await client.post(f"{API}/freeBusy", json=body, headers=headers)
            response.raise_for_status()
        entry = response.json().get("calendars", {}).get(calendar_id, {})
        if entry.get("errors"):  # a calendar we cannot see is not a calendar with nothing on it
            raise RuntimeError(f"Google cannot read the calendar: {entry['errors'][0]['reason']}")
        return [
            Busy(datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"]))
            for b in entry.get("busy", [])
        ]

    async def create_event(
        self,
        refresh_token: str,
        calendar_id: str,
        event_id: str,
        title: str,
        description: str,
        start: datetime,
        end: datetime,
    ) -> bool:
        body = {
            "id": event_id,
            "summary": title,
            "description": description,
            "start": {"dateTime": start.isoformat(), "timeZone": IST},
            "end": {"dateTime": end.isoformat(), "timeZone": IST},
        }
        async with self._client() as client:
            headers = await self._headers(client, refresh_token)
            url = f"{API}/calendars/{quote(calendar_id, safe='')}/events"
            response = await client.post(url, json=body, headers=headers)
            if response.status_code == 409:
                return False
            response.raise_for_status()
        return True

    async def delete_event(self, refresh_token: str, calendar_id: str, event_id: str) -> None:
        async with self._client() as client:
            headers = await self._headers(client, refresh_token)
            url = f"{API}/calendars/{quote(calendar_id, safe='')}/events/{quote(event_id)}"
            response = await client.delete(url, headers=headers)
            if response.status_code not in (404, 410):
                response.raise_for_status()
