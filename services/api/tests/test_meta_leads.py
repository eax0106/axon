import hashlib
import hmac
import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.providers.leads.meta_lead_ads import GRAPH, MetaLeadAds

from .conftest import sql
from .helpers import live_employee, seed, signup

APP_SECRET = "app-secret"  # noqa: S105 - test credential
VERIFY = "verify-me"
FORM = "1234567890"
WEBHOOK = {
    "object": "page",
    "entry": [
        {
            "id": "page-1",
            "time": 1730000000,
            "changes": [
                {
                    "field": "leadgen",
                    "value": {
                        "leadgen_id": "lead-111",
                        "page_id": "page-1",
                        "form_id": FORM,
                        "ad_id": "ad-1",
                        "created_time": 1730000000,
                    },
                }
            ],
        }
    ],
}
GRAPH_LEAD = {
    "created_time": "2026-11-02T05:30:00+0000",
    "id": "lead-111",
    "form_id": FORM,
    "field_data": [
        {"name": "full_name", "values": ["Ravi Kumar"]},
        {"name": "phone_number", "values": ["+919876543210"]},
        {"name": "budget", "values": ["5 lakh"]},
    ],
}


def signed(body: dict[str, Any], secret: str = APP_SECRET) -> tuple[bytes, dict[str, str]]:
    raw = json.dumps(body).encode()
    digest = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {"X-Hub-Signature-256": f"sha256={digest}", "Content-Type": "application/json"}


class Graph:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.status = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json=GRAPH_LEAD)


@pytest.fixture
def api(
    db_client: TestClient, migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, Graph]]:
    seed(migrated_url)
    monkeypatch.setenv("META_APP_ID", "app-1")
    monkeypatch.setenv("META_APP_SECRET", APP_SECRET)
    monkeypatch.setenv("META_VERIFY_TOKEN", VERIFY)
    graph = Graph()
    transport = httpx.MockTransport(graph.handler)
    monkeypatch.setattr(MetaLeadAds, "_client", lambda self: httpx.AsyncClient(transport=transport))
    yield db_client, graph


def connect(
    client: TestClient, url: str, variables: tuple[str, ...] = ("budget",)
) -> tuple[str, dict[str, str]]:
    owner = signup(client)
    employee = live_employee(client, url, owner, variables=variables)
    response = client.put(
        f"/employees/{employee}/instant/meta",
        json={"form_id": FORM, "page_access_token": "page-token"},
        headers=owner,
    )
    assert response.status_code == 200
    return employee, owner


def test_the_verification_handshake_echoes_the_challenge_only_for_our_token(
    api: tuple[TestClient, Graph],
) -> None:
    client, _ = api
    ok = client.get(
        "/lead-intake/meta",
        params={"hub.mode": "subscribe", "hub.verify_token": VERIFY, "hub.challenge": "42"},
    )
    assert ok.status_code == 200 and ok.text == "42"
    for params in (
        {"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "42"},
        {"hub.mode": "unsubscribe", "hub.verify_token": VERIFY, "hub.challenge": "42"},
        {},
    ):
        assert client.get("/lead-intake/meta", params=params).status_code == 403


def test_a_signed_lead_is_fetched_and_run_through_intake(
    api: tuple[TestClient, Graph], migrated_url: str
) -> None:
    client, graph = api
    employee, owner = connect(client, migrated_url)
    raw, headers = signed(WEBHOOK)
    response = client.post("/lead-intake/meta", content=raw, headers=headers)
    assert response.status_code == 200 and response.json() == {"handled": 1}
    request = graph.requests[0]
    assert str(request.url.copy_with(query=None)) == f"{GRAPH}/lead-111"
    assert dict(request.url.params) == {"access_token": "page-token"}
    assert (
        sql(migrated_url, "SELECT name || phone || fields::text FROM leads")
        == 'Ravi Kumar+919876543210{"budget": "5 lakh"}'
    )
    log = client.get(f"/employees/{employee}/instant/intake-log", headers=owner).json()
    assert [(e["source"], e["status"]) for e in log] == [("meta", "accepted")]
    assert sql(migrated_url, "SELECT status::text FROM calls") == "queued"


def test_unsigned_tampered_and_wrongly_signed_posts_are_refused(
    api: tuple[TestClient, Graph], migrated_url: str
) -> None:
    client, graph = api
    connect(client, migrated_url)
    raw, headers = signed(WEBHOOK)
    cases = [
        (raw, {"Content-Type": "application/json"}),
        (raw + b" ", headers),  # body changed after signing
        (raw, {**headers, "X-Hub-Signature-256": "sha256=" + "0" * 64}),
        (
            raw,
            {
                **headers,
                "X-Hub-Signature-256": headers["X-Hub-Signature-256"].removeprefix("sha256="),
            },
        ),
        *[(r, h) for r, h in [signed(WEBHOOK, secret="not-the-app-secret")]],  # noqa: S106
    ]
    for body, hdrs in cases:
        assert client.post("/lead-intake/meta", content=body, headers=hdrs).status_code == 401
    assert graph.requests == [] and sql(migrated_url, "SELECT count(*) FROM lead_intake_log") == 0


def test_a_form_nobody_connected_is_ignored(
    api: tuple[TestClient, Graph], migrated_url: str
) -> None:
    client, graph = api
    raw, headers = signed(WEBHOOK)
    assert client.post("/lead-intake/meta", content=raw, headers=headers).json() == {"handled": 0}
    assert graph.requests == []


def test_a_graph_failure_is_a_502_so_meta_retries(
    api: tuple[TestClient, Graph], migrated_url: str
) -> None:
    client, graph = api
    connect(client, migrated_url)
    graph.status = 400
    raw, headers = signed(WEBHOOK)
    assert client.post("/lead-intake/meta", content=raw, headers=headers).status_code == 502


def test_a_form_can_feed_only_one_employee(
    api: tuple[TestClient, Graph], migrated_url: str
) -> None:
    client, _ = api
    _, owner = connect(client, migrated_url)
    other = live_employee(client, migrated_url, owner, number="+911400000002")
    response = client.put(
        f"/employees/{other}/instant/meta",
        json={"form_id": FORM, "page_access_token": "t"},
        headers=owner,
    )
    assert response.status_code == 409


def test_events_are_read_from_the_leadgen_changes_only() -> None:
    provider = MetaLeadAds()
    other = {"entry": [{"changes": [{"field": "feed", "value": {"leadgen_id": "x"}}]}]}
    assert provider.events(other) == [] and provider.events({}) == []
    assert [(e.leadgen_id, e.form_id) for e in provider.events(WEBHOOK)] == [("lead-111", FORM)]


def test_health_reads_the_app_with_its_own_token(api: tuple[TestClient, Graph]) -> None:
    import asyncio

    _, graph = api
    asyncio.run(MetaLeadAds().health())
    assert str(graph.requests[0].url.copy_with(query=None)) == f"{GRAPH}/app"
    assert dict(graph.requests[0].url.params) == {"access_token": f"app-1|{APP_SECRET}"}


def test_without_meta_keys_the_webhook_is_503(db_client: TestClient, no_keys: None) -> None:
    assert db_client.get("/lead-intake/meta").status_code == 503
    assert db_client.post("/lead-intake/meta", content=b"{}").json()["kind"] == "leads"
