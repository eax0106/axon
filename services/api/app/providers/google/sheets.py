"""Google Sheets: read rows (lead source, in-call lookups) and append rows (in-call writes).

Values are read with GET https://sheets.googleapis.com/v4/spreadsheets/{id}/values/{range} and
added with POST .../values/{range}:append, both with a Bearer access token.
"""

from urllib.parse import quote

import httpx

from app.providers.base import SheetsProvider
from app.providers.google import oauth

SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
WRITE_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
TIMEOUT_S = oauth.TIMEOUT_S


def consent_url(redirect_uri: str, state: str) -> str:
    """Where to send the owner to let us read their sheet (the lead source: read-only)."""
    return oauth.consent_url(redirect_uri, state, SCOPE)


class GoogleSheets(SheetsProvider):
    name = "google"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=TIMEOUT_S, transport=self._transport)

    async def health(self) -> None:
        async with self._client() as client:
            await oauth.check_client(client)

    async def exchange_code(self, code: str, redirect_uri: str) -> str:
        async with self._client() as client:
            return (await oauth.exchange(client, code, redirect_uri)).refresh_token

    async def read_rows(
        self, refresh_token: str, sheet_id: str, cell_range: str
    ) -> list[list[str]]:
        async with self._client() as client:
            token = await oauth.access_token(client, refresh_token)
            url = f"{SHEETS}/{quote(sheet_id, safe='')}/values/{quote(cell_range, safe='')}"
            response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            response.raise_for_status()
        return [[str(cell) for cell in row] for row in response.json().get("values", [])]

    async def append_row(
        self, refresh_token: str, sheet_id: str, cell_range: str, row: list[str]
    ) -> None:
        # RAW: Sheets keeps the text as given, so a caller's "=HYPERLINK(...)" is not a formula.
        url = f"{SHEETS}/{quote(sheet_id, safe='')}/values/{quote(cell_range, safe='')}:append"
        query = {"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"}
        async with self._client() as client:
            token = await oauth.access_token(client, refresh_token)
            response = await client.post(
                url,
                params=query,
                json={"values": [row]},
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
