"""Google Sheets as a lead source (OAuth2 web-server flow, read-only scope).

Token endpoint https://oauth2.googleapis.com/token (form-encoded); values are read with
GET https://sheets.googleapis.com/v4/spreadsheets/{id}/values/{range} and a Bearer access token.
"""

import os
from urllib.parse import quote, urlencode

import httpx

from app.providers.base import SheetsProvider

TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - a URL, not a secret
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
TIMEOUT_S = 15.0


def consent_url(redirect_uri: str, state: str) -> str:
    """Where to send the owner to let us read their sheet (offline access gives a refresh token)."""
    query = {
        "client_id": os.environ["GOOGLE_OAUTH_CLIENT_ID"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(query)}"


class GoogleSheets(SheetsProvider):
    name = "google"

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=TIMEOUT_S, transport=self._transport)

    def _credentials(self) -> dict[str, str]:
        return {
            "client_id": os.environ["GOOGLE_OAUTH_CLIENT_ID"],
            "client_secret": os.environ["GOOGLE_OAUTH_CLIENT_SECRET"],
        }

    async def health(self) -> None:
        # No user is signed in here, so probe the token endpoint with a dummy refresh token: Google
        # answers invalid_grant when the client id and secret are right and invalid_client if not.
        form = {**self._credentials(), "grant_type": "refresh_token", "refresh_token": "probe"}
        async with self._client() as client:
            response = await client.post(TOKEN_URL, data=form)
        error = response.json().get("error") if response.status_code in (400, 401) else None
        if error != "invalid_grant":
            raise RuntimeError(f"Google rejected the OAuth client: {error or response.status_code}")

    async def exchange_code(self, code: str, redirect_uri: str) -> str:
        form = {
            **self._credentials(),
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }
        async with self._client() as client:
            response = await client.post(TOKEN_URL, data=form)
            response.raise_for_status()
        refresh = response.json().get("refresh_token")
        if not refresh:
            raise RuntimeError("Google returned no refresh token; ask again with prompt=consent")
        return str(refresh)

    async def _access_token(self, client: httpx.AsyncClient, refresh_token: str) -> str:
        form = {
            **self._credentials(),
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        response = await client.post(TOKEN_URL, data=form)
        response.raise_for_status()
        return str(response.json()["access_token"])

    async def read_rows(
        self, refresh_token: str, sheet_id: str, cell_range: str
    ) -> list[list[str]]:
        async with self._client() as client:
            token = await self._access_token(client, refresh_token)
            url = f"{SHEETS}/{quote(sheet_id, safe='')}/values/{quote(cell_range, safe='')}"
            response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            response.raise_for_status()
        return [[str(cell) for cell in row] for row in response.json().get("values", [])]
