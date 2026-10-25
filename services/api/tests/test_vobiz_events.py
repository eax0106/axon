import base64
import hashlib
import hmac
import itertools
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.instant import public
from app.providers.telephony.vobiz import BASE_URL, VobizTelephony

from .conftest import sql
from .helpers import live_employee, seed, signup

URL = "https://api.example.in/vobiz/events"
TOKEN = "vobiz-token"  # noqa: S105 - test credential
_nonces = itertools.count(10_000_000_000_000_000_000)


def sign(url: str = URL, nonce: str | None = None, token: str = TOKEN) -> dict[str, str]:
    nonce = nonce or str(next(_nonces))
    digest = hmac.new(token.encode(), f"{url}.{nonce}".encode(), hashlib.sha256).digest()
    return {
        "X-Vobiz-Signature-V3": base64.b64encode(digest).decode(),
        "X-Vobiz-Signature-V3-Nonce": nonce,
    }


class Cdr:
    """The carrier's record of the call, keyed by the call's own id (`leg-1`), not the id of the
    dial request (`req-1`)."""

    def __init__(self) -> None:
        self.record: dict[str, Any] | None = {
            "billsec": 0,
            "duration": 25,
            "hangup_cause": "USER_BUSY",
        }
        self.asked: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request.url.path)
        if request.url.path.endswith("/leg-1") and self.record is not None:
            return httpx.Response(200, json=self.record)
        return httpx.Response(404)


@pytest.fixture
def api(
    db_client: TestClient, migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, Cdr]]:
    seed(migrated_url)
    monkeypatch.setenv("AXON_API_PUBLIC_URL", "https://api.example.in")
    monkeypatch.setenv("VOBIZ_AUTH_ID", "MA_TEST")
    monkeypatch.setenv("VOBIZ_AUTH_TOKEN", TOKEN)
    cdr = Cdr()
    transport = httpx.MockTransport(cdr.handler)
    monkeypatch.setattr(
        VobizTelephony,
        "_client",
        lambda self: httpx.AsyncClient(
            base_url=f"{BASE_URL}/Account/MA_TEST", headers=self._headers, transport=transport
        ),
    )
    public._seen_nonces.clear()
    yield db_client, cdr


def ringing_call(api: TestClient, url: str) -> None:
    owner = signup(api)
    employee = live_employee(api, url, owner)
    account = sql(url, "SELECT account_id FROM employees")
    lead = sql(
        url,
        "INSERT INTO leads (account_id, phone) VALUES (:a, '+919876543210') RETURNING id",
        {"a": account},
    )
    sql(
        url,
        "INSERT INTO calls (account_id, employee_id, lead_id, direction, channel, status,"
        " attempt, carrier_call_id)"
        " VALUES (:a, :e, :l, 'outbound', 'instant', 'ringing', 1, 'req-1')",
        {"a": account, "e": employee, "l": lead},
    )


def hangup(
    client: TestClient, headers: dict[str, str], uuid: str = "leg-1", body: str | None = None
) -> Any:
    form = (
        body
        if body is not None
        else f"CallUUID={uuid}&RequestUUID=req-1&Event=Hangup&CallStatus=completed"
    )
    return client.post(
        "/vobiz/events",
        content=form,
        headers={**headers, "Content-Type": "application/x-www-form-urlencoded"},
    )


def statuses(url: str) -> list[str]:
    return [
        r
        for r in sql(url, "SELECT string_agg(status::text, ',' ORDER BY attempt) FROM calls").split(
            ","
        )
    ]


def test_a_signed_callback_settles_the_call_from_the_carrier_record(
    api: tuple[TestClient, Cdr], migrated_url: str
) -> None:
    client, cdr = api
    ringing_call(client, migrated_url)
    assert hangup(client, sign()).status_code == 200
    assert cdr.asked == ["/api/v1/Account/MA_TEST/cdr/leg-1"]  # the call id, not the request id
    assert statuses(migrated_url) == ["busy", "queued"]  # settled, and the retry is queued
    assert sql(migrated_url, "SELECT duration_s FROM calls WHERE attempt = 1") == 25


def test_the_unsigned_body_is_never_believed(
    api: tuple[TestClient, Cdr], migrated_url: str
) -> None:
    client, cdr = api
    ringing_call(client, migrated_url)
    cdr.record = {"billsec": 0, "duration": 20, "hangup_cause": "NO_ANSWER"}
    # The body says completed with a long duration; the carrier's own record says nobody answered.
    body = "CallUUID=leg-1&RequestUUID=req-1&CallStatus=completed&Duration=600&Status=completed"
    assert hangup(client, sign(), body=body).status_code == 200
    assert statuses(migrated_url)[0] == "no_answer"


def test_a_callback_without_a_valid_signature_is_refused_before_anything_is_read(
    api: tuple[TestClient, Cdr], migrated_url: str
) -> None:
    client, cdr = api
    ringing_call(client, migrated_url)
    good = sign()
    for headers in (
        {},
        {"X-Vobiz-Signature-V3": good["X-Vobiz-Signature-V3"]},  # nonce missing
        {"X-Vobiz-Signature-V3-Nonce": good["X-Vobiz-Signature-V3-Nonce"]},  # signature missing
        sign(token="someone-elses-token"),  # noqa: S106 - test credential
        sign(url="https://api.example.in/vobiz/other"),
        {**good, "X-Vobiz-Signature-V3-Nonce": "1"},  # signature for another nonce
        {"X-Vobiz-Signature-V2": good["X-Vobiz-Signature-V3"], "X-Vobiz-Signature-V2-Nonce": "1"},
    ):
        assert hangup(client, headers).status_code == 401, headers
    assert cdr.asked == [] and statuses(migrated_url) == ["ringing"]


def test_a_replayed_nonce_is_refused(api: tuple[TestClient, Cdr], migrated_url: str) -> None:
    client, _ = api
    ringing_call(client, migrated_url)
    headers = sign()
    assert hangup(client, headers).status_code == 200
    assert hangup(client, headers).status_code == 409


def test_vobiz_retrying_with_a_fresh_nonce_does_not_double_retry_the_lead(
    api: tuple[TestClient, Cdr], migrated_url: str
) -> None:
    client, _ = api
    ringing_call(client, migrated_url)
    assert hangup(client, sign()).status_code == 200
    assert hangup(client, sign()).status_code == 200
    assert statuses(migrated_url) == ["busy", "queued"]


def test_unknown_calls_are_ignored_and_a_missing_record_leaves_the_call_for_the_reaper(
    api: tuple[TestClient, Cdr], migrated_url: str
) -> None:
    client, cdr = api
    ringing_call(client, migrated_url)
    assert hangup(client, sign(), body="CallUUID=nope&RequestUUID=nada").status_code == 200
    assert hangup(client, sign(), body="nothing=useful").status_code == 200
    assert statuses(migrated_url) == ["ringing"]
    cdr.record = None  # the carrier has not written the record yet
    assert hangup(client, sign()).status_code == 200
    assert statuses(migrated_url) == ["ringing"]


def test_without_carrier_keys_or_a_public_url_it_is_503(
    api: tuple[TestClient, Cdr], migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = api
    monkeypatch.delenv("AXON_API_PUBLIC_URL")
    response = hangup(client, sign())
    assert response.status_code == 503 and response.json()["missing_keys"] == [
        "AXON_API_PUBLIC_URL"
    ]
    monkeypatch.setenv("AXON_API_PUBLIC_URL", "https://api.example.in")
    monkeypatch.delenv("VOBIZ_AUTH_TOKEN")
    assert hangup(client, sign()).json()["error"] == "provider_not_configured"


def test_a_callback_naming_only_the_request_id_finds_the_call_but_cannot_guess_the_outcome(
    api: tuple[TestClient, Cdr], migrated_url: str
) -> None:
    """Never turn "no record yet" into "not answered": the call stays as it is."""
    client, cdr = api
    ringing_call(client, migrated_url)
    assert hangup(client, sign(), body="RequestUUID=req-1&Event=Hangup").status_code == 200
    assert statuses(migrated_url) == ["ringing"]
    assert cdr.asked == ["/api/v1/Account/MA_TEST/cdr/req-1"]


def test_the_call_id_from_the_callback_is_remembered_for_later_lookups(
    api: tuple[TestClient, Cdr], migrated_url: str
) -> None:
    client, cdr = api
    ringing_call(client, migrated_url)
    cdr.record = None  # not written yet
    assert hangup(client, sign()).status_code == 200
    assert sql(migrated_url, "SELECT carrier_leg_id FROM calls") == "leg-1"
    cdr.record = {"billsec": 12, "duration": 30, "hangup_cause": "NORMAL_CLEARING"}
    # A second callback that names the call by its call id alone still finds the row.
    assert hangup(client, sign(), body="CallUUID=leg-1").status_code == 200
    assert statuses(migrated_url) == ["completed"]
