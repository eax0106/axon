"""Google's OAuth2 web-server flow, shared by the Sheets and Calendar adapters.

Token endpoint https://oauth2.googleapis.com/token (form-encoded), refresh tokens for offline use.
"""

import os
from urllib.parse import urlencode

import httpx

from app.providers.base import OAuthGrant

TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - a URL, not a secret
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TIMEOUT_S = 15.0


def credentials() -> dict[str, str]:
    return {
        "client_id": os.environ["GOOGLE_OAUTH_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_OAUTH_CLIENT_SECRET"],
    }


def consent_url(redirect_uri: str, state: str, scope: str) -> str:
    """Where to send the owner to let us use their Google data (offline access gives a refresh
    token)."""
    query = {
        "client_id": os.environ["GOOGLE_OAUTH_CLIENT_ID"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(query)}"


async def exchange(client: httpx.AsyncClient, code: str, redirect_uri: str) -> OAuthGrant:
    form = {
        **credentials(),
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    response = await client.post(TOKEN_URL, data=form)
    response.raise_for_status()
    body = response.json()
    if not body.get("refresh_token"):
        raise RuntimeError("Google returned no refresh token; ask again with prompt=consent")
    return OAuthGrant(str(body["refresh_token"]), frozenset(str(body.get("scope", "")).split()))


async def access_token(client: httpx.AsyncClient, refresh_token: str) -> str:
    form = {**credentials(), "grant_type": "refresh_token", "refresh_token": refresh_token}
    response = await client.post(TOKEN_URL, data=form)
    response.raise_for_status()
    return str(response.json()["access_token"])


async def revoke(client: httpx.AsyncClient, token: str) -> None:
    """Take the permission back at Google. A token already revoked is not an error."""
    response = await client.post(REVOKE_URL, data={"token": token})
    if response.status_code != 400:  # 400 invalid_token: nothing left to revoke
        response.raise_for_status()


async def check_client(client: httpx.AsyncClient) -> None:
    """No user is signed in here, so probe the token endpoint with a dummy refresh token: Google
    answers invalid_grant when the client id and secret are right and invalid_client if not."""
    form = {**credentials(), "grant_type": "refresh_token", "refresh_token": "probe"}
    response = await client.post(TOKEN_URL, data=form)
    error = response.json().get("error") if response.status_code in (400, 401) else None
    if error != "invalid_grant":
        raise RuntimeError(f"Google rejected the OAuth client: {error or response.status_code}")
