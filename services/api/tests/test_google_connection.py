import uuid
from typing import Any
from urllib.parse import parse_qs

from fastapi.testclient import TestClient

from app.employees import tickets
from app.providers.google import calendar as g_calendar
from app.providers.google import sheets as g_sheets

from .actions_support import REDIRECT, Google, connect_google
from .conftest import sql
from .helpers import account_id, add_member, signup


def consent_query(client: TestClient, owner: dict[str, str], **params: Any) -> dict[str, list[str]]:
    response = client.get(
        "/integrations/google/consent-url",
        params={"redirect_uri": REDIRECT, "services": ["calendar", "sheets"], **params},
        headers=owner,
    )
    assert response.status_code == 200, response.text
    return parse_qs(response.json()["url"].split("?", 1)[1])


def test_nothing_is_connected_at_first(actions_api: tuple[TestClient, Google]) -> None:
    client, _ = actions_api
    owner = signup(client)
    status = client.get("/integrations/google", headers=owner).json()
    assert status == {"connected": False, "calendar": False, "sheets": False}


def test_the_consent_link_asks_only_for_the_chosen_services_with_offline_access(
    actions_api: tuple[TestClient, Google],
) -> None:
    client, _ = actions_api
    owner = signup(client)
    both = consent_query(client, owner)
    assert set(both["scope"][0].split()) == {*g_calendar.SCOPES, g_sheets.WRITE_SCOPE}
    assert both["access_type"] == ["offline"] and both["redirect_uri"] == [REDIRECT]
    only = consent_query(client, owner, services=["sheets"])
    assert only["scope"] == [g_sheets.WRITE_SCOPE]
    refused = client.get(
        "/integrations/google/consent-url",
        params={"redirect_uri": REDIRECT, "services": ["drive"]},
        headers=owner,
    )
    assert refused.status_code == 422


def test_connecting_stores_the_grant_and_shows_what_google_really_allowed(
    actions_api: tuple[TestClient, Google], migrated_url: str
) -> None:
    client, google = actions_api
    owner = signup(client)
    google.granted = g_calendar.SCOPES[0]  # the owner unticked Sheets and free/busy
    assert connect_google(client, owner) == {"connected": True, "calendar": True, "sheets": False}
    assert client.get("/integrations/google", headers=owner).json()["sheets"] is False
    assert sql(migrated_url, "SELECT refresh_token FROM google_connections") == "rt-1"
    google.granted = "https://www.googleapis.com/auth/userinfo.email"
    again = client.get(
        "/integrations/google/consent-url",
        params={"redirect_uri": REDIRECT, "services": ["calendar"]},
        headers=owner,
    ).json()["url"]
    state = parse_qs(again.split("?", 1)[1])["state"][0]
    body = {"code": "c", "redirect_uri": REDIRECT, "state": state}
    nothing = client.post("/integrations/google/connect", json=body, headers=owner)
    assert nothing.status_code == 400  # and the earlier connection is untouched
    assert client.get("/integrations/google", headers=owner).json()["calendar"] is True


def test_a_state_made_for_someone_else_or_for_a_sheet_lead_source_is_refused(
    actions_api: tuple[TestClient, Google], migrated_url: str
) -> None:
    client, _ = actions_api
    owner = signup(client)
    other = signup(client, "other@example.com", "Other")
    mine = uuid.UUID(account_id(client, owner))
    theirs = uuid.UUID(account_id(client, other))
    user = uuid.UUID(
        str(sql(migrated_url, "SELECT id FROM users WHERE email = 'owner@example.com'"))
    )
    body = {"code": "c", "redirect_uri": REDIRECT}
    for state in (
        tickets.issue_oauth_state(user, theirs, purpose="google"),  # another account's
        tickets.issue_oauth_state(user, mine),  # the lead-source kind
        "forged",
    ):
        refused = client.post(
            "/integrations/google/connect", json={**body, "state": state}, headers=owner
        )
        assert refused.status_code == 400
    assert client.get("/integrations/google", headers=owner).json()["connected"] is False


def test_disconnecting_revokes_the_permission_at_google_and_forgets_it(
    actions_api: tuple[TestClient, Google], migrated_url: str
) -> None:
    client, google = actions_api
    owner = signup(client)
    connect_google(client, owner)
    assert client.delete("/integrations/google", headers=owner).status_code == 204
    assert google.revoked == ["rt-1"]
    assert sql(migrated_url, "SELECT count(*) FROM google_connections") == 0
    assert client.delete("/integrations/google", headers=owner).status_code == 204


def test_only_the_owner_connects_but_a_member_can_see_the_state(
    actions_api: tuple[TestClient, Google], migrated_url: str
) -> None:
    client, _ = actions_api
    owner = signup(client)
    member = add_member(client, migrated_url, owner)
    connect_google(client, owner)
    assert client.get("/integrations/google", headers=member).json()["connected"] is True
    consent = client.get(
        "/integrations/google/consent-url",
        params={"redirect_uri": REDIRECT, "services": ["sheets"]},
        headers=member,
    )
    assert consent.status_code == 403
    assert client.delete("/integrations/google", headers=member).status_code == 403


def test_without_the_google_client_the_answer_is_503(api: TestClient) -> None:
    owner = signup(api)
    response = api.get(
        "/integrations/google/consent-url",
        params={"redirect_uri": REDIRECT, "services": ["sheets"]},
        headers=owner,
    )
    assert response.status_code == 503
    assert response.json()["error"] == "provider_not_configured"
