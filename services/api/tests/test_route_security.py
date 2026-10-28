"""Every operation in the OpenAPI spec is swept: who may call it without proving who they are."""

import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.main import app

from .test_auth import _auth, _signup

# Answer anonymous callers on purpose.
OPEN = {
    "POST /auth/signup": "creates an account",
    "POST /auth/login": "signs in",
    "GET /healthz": "liveness probe",
    "GET /readyz": "readiness probe",
    "GET /v1/openapi.json": "public API reference",
    "GET /v1/postman.json": "public API reference",
}
# Called by outside services or people with no session. Each must refuse a call that carries no
# proof, and a caller who does not match is never answered 2xx.
PROOF = {
    "GET /lead-intake/meta": "Meta's webhook handshake: verify token",
    "POST /lead-intake/meta": "Meta's lead webhook: HMAC signature",
    "POST /lead-intake/{connection_id}": "a lead source's secret header",
    "POST /vobiz/events": "the carrier's call events: signature",
    "POST /webhooks/razorpay": "Razorpay's payment webhook: signature",
    "GET /public/otp/{token}": "the one-time page a phone owner opens: random token",
    "POST /public/otp/{token}": "the one-time page a phone owner opens: random token",
}
APP_DIR = Path(__file__).parents[1] / "app"
SAMPLE_ID = "00000000-0000-0000-0000-000000000001"


def operations() -> list[tuple[str, str]]:
    spec: dict[str, Any] = app.openapi()
    return [(m.upper(), p) for p, ops in spec["paths"].items() for m in ops]


def url_of(path: str) -> str:
    path = re.sub(r"\{\w*id\}", SAMPLE_ID, path)
    return re.sub(r"\{\w+\}", "1", path)


def call(client: TestClient, method: str, path: str, headers: dict[str, str] | None = None) -> int:
    body: dict[str, Any] | None = {} if method in ("POST", "PUT", "PATCH") else None
    return client.request(method, url_of(path), json=body, headers=headers).status_code


def test_the_lists_name_only_routes_that_exist() -> None:
    names = {f"{m} {p}" for m, p in operations()}
    assert sorted((OPEN | PROOF).keys() - names) == []


def test_an_anonymous_caller_is_refused_everywhere_but_the_listed_routes(
    db_client: TestClient,
) -> None:
    open_to_all = []
    for method, path in operations():
        code = call(db_client, method, path)
        name = f"{method} {path}"
        if name in OPEN:
            continue
        if name in PROOF:
            assert code >= 400 and code != 500, f"{name} answered {code} with no proof"
        elif code not in (401, 403):
            open_to_all.append(f"{name} -> {code}")
    assert open_to_all == []


def test_a_signed_in_member_who_is_not_staff_is_refused_every_admin_route(
    db_client: TestClient,
) -> None:
    headers = _auth(_signup(db_client))
    admin = [(m, p) for m, p in operations() if p.startswith("/admin/")]
    assert len(admin) > 20
    allowed = [f"{m} {p}" for m, p in admin if call(db_client, m, p, headers) != 403]
    assert allowed == []


def test_a_session_token_does_not_open_the_public_api_and_a_key_does_not_open_the_dashboard(
    db_client: TestClient,
) -> None:
    session = _auth(_signup(db_client))
    made = db_client.post("/developer/keys", json={"name": "sweep"}, headers=session)
    key = {"Authorization": f"Bearer {made.json()['key']}"}
    assert db_client.get("/v1/account", headers=key).status_code == 200
    assert db_client.get("/v1/account", headers=session).status_code == 401
    dashboard = [(m, p) for m, p in operations() if not p.startswith("/v1/")]
    accepted = [
        f"{m} {p}"
        for m, p in dashboard
        if f"{m} {p}" not in OPEN | PROOF and call(db_client, m, p, key) not in (401, 403)
    ]
    assert accepted == []


def test_a_websocket_without_a_token_is_closed_and_the_live_call_socket_is_swept(
    db_client: TestClient,
) -> None:
    # WebSockets are not in the OpenAPI spec, so the operation sweep never sees them; find them in
    # the source so a new one is swept too.
    sockets = sorted(
        {
            path
            for file in APP_DIR.rglob("*.py")
            for path in re.findall(r"\.websocket\(\s*\"([^\"]+)\"", file.read_text("utf-8"))
        }
    )
    assert "/calls/{call_id}/live" in sockets
    for path in sockets:
        with pytest.raises(WebSocketDisconnect) as closed:
            with db_client.websocket_connect(url_of(path)) as ws:
                ws.receive_text()
        assert closed.value.code in (1008, 4401, 403), f"{path} closed with {closed.value.code}"


@pytest.mark.parametrize("name", sorted(PROOF))
def test_every_proof_route_has_a_reason(name: str) -> None:
    assert PROOF[name]
