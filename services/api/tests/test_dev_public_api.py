import os
import uuid
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.developer import keys

from .conftest import sql
from .developer_support import NOW, bearer, make_key
from .helpers import account_id, add_call, add_lead, live_employee, signup

CALLER = "+919876543210"


def setup(api: TestClient, url: str, **kw: Any) -> tuple[dict[str, str], dict[str, str], str]:
    owner = signup(api, **kw)
    employee = live_employee(api, url, owner, variables=("budget",))
    return owner, bearer(make_key(api, owner)), employee


def test_account_and_employees_are_readable_and_only_for_the_keys_account(
    api: TestClient, migrated_url: str
) -> None:
    _, key, employee = setup(api, migrated_url)
    other = signup(api, email="b@example.com", account="Other")
    other_employee = live_employee(api, migrated_url, other, number="+911400000002", variables=())
    assert api.get("/v1/account", headers=key).json()["name"] == "Acme"
    assert float(api.get("/v1/account", headers=key).json()["credit_balance"]) == 50
    listed = api.get("/v1/employees", headers=key).json()
    assert [e["id"] for e in listed] == [employee]
    shown = api.get(f"/v1/employees/{employee}", headers=key).json()
    assert shown["phone_number"] == "+911400000001"
    assert shown["pre_call_variables"] == ["budget"] and shown["status"] == "live"
    assert api.get(f"/v1/employees/{other_employee}", headers=key).status_code == 404
    assert api.get(f"/v1/employees/{uuid.uuid4()}", headers=key).status_code == 404


def test_calls_list_newest_first_with_filters_a_cursor_and_no_test_calls(
    api: TestClient, migrated_url: str
) -> None:
    owner, key, employee = setup(api, migrated_url)
    account = account_id(api, owner)
    lead = add_lead(migrated_url, account, CALLER, "Asha")
    stamps = [NOW - timedelta(hours=h) for h in range(5)]
    made = [
        add_call(migrated_url, account, employee, lead, created_at=at, outcome="interested")
        for at in stamps
    ]
    add_call(
        migrated_url, account, employee, lead, is_test=True, created_at=NOW + timedelta(minutes=2)
    )
    inbound = add_call(
        migrated_url, account, employee, None, direction="inbound",
        created_at=NOW + timedelta(minutes=1),
        status="no_answer",
    )  # fmt: skip
    sql(
        migrated_url,
        "UPDATE calls SET caller_phone = '+919000000009' WHERE id = :i",
        {"i": inbound},
    )

    first = api.get("/v1/calls?limit=3", headers=key).json()
    assert len(first["data"]) == 3 and first["next_cursor"]
    assert first["data"][0]["id"] == str(inbound)  # newest first
    second = api.get(f"/v1/calls?limit=3&cursor={first['next_cursor']}", headers=key).json()
    seen = [c["id"] for c in first["data"] + second["data"]]
    assert len(seen) == len(set(seen)) == 6 and second["next_cursor"] is None
    assert set(seen) == {str(c) for c in made} | {str(inbound)}  # the test call is not there

    assert api.get("/v1/calls?direction=inbound", headers=key).json()["data"][0]["phone"] == (
        "+919000000009"
    )
    assert len(api.get("/v1/calls?status=completed", headers=key).json()["data"]) == 5
    since = (NOW - timedelta(hours=1, minutes=1)).isoformat()
    assert len(api.get("/v1/calls", params={"since": since}, headers=key).json()["data"]) == 3
    assert api.get("/v1/calls?cursor=garbage", headers=key).status_code == 422
    assert api.get("/v1/calls?limit=1000", headers=key).status_code == 422


def test_one_call_has_its_transcript_and_a_test_or_foreign_call_is_a_404(
    api: TestClient, migrated_url: str
) -> None:
    owner, key, employee = setup(api, migrated_url)
    account = account_id(api, owner)
    lead = add_lead(migrated_url, account, CALLER, "Asha")
    turns = [{"role": "assistant", "text": "Hello"}, {"role": "user", "text": "Hi there"}]
    call = add_call(
        migrated_url, account, employee, lead, transcript=turns, captured={"budget": "80 lakh"},
        summary="Wants a visit",
    )  # fmt: skip
    test_call = add_call(migrated_url, account, employee, lead, is_test=True)
    shown = api.get(f"/v1/calls/{call}", headers=key).json()
    assert shown["transcript"] == turns and shown["captured"] == {"budget": "80 lakh"}
    assert shown["phone"] == CALLER and shown["voicemail"] is False
    assert api.get(f"/v1/calls/{test_call}", headers=key).status_code == 404
    other = signup(api, email="b@example.com", account="Other")
    foreign = bearer(make_key(api, other))
    assert api.get(f"/v1/calls/{call}", headers=foreign).status_code == 404
    assert api.get("/v1/calls", headers=foreign).json()["data"] == []


def test_leads_and_campaigns_are_listed_and_filtered(api: TestClient, migrated_url: str) -> None:
    owner, key, employee = setup(api, migrated_url)
    account = account_id(api, owner)
    lead = add_lead(migrated_url, account, CALLER, "Asha", budget="80 lakh")
    add_lead(migrated_url, account, "+919876543211", None)
    assert len(api.get("/v1/leads", headers=key).json()["data"]) == 2
    only = api.get("/v1/leads", params={"phone": CALLER}, headers=key).json()["data"]
    assert [x["id"] for x in only] == [str(lead)] and only[0]["variables"] == {"budget": "80 lakh"}
    assert api.get(f"/v1/leads/{lead}", headers=key).json()["name"] == "Asha"
    assert api.get(f"/v1/leads/{uuid.uuid4()}", headers=key).status_code == 404

    for name, status in (("Diwali", "running"), ("Eid", "paused")):
        sql(
            migrated_url,
            "INSERT INTO campaigns (account_id, employee_id, name, status) VALUES (:a, :e, :n, :s)",
            {"a": account, "e": employee, "n": name, "s": status},
        )
    assert len(api.get("/v1/campaigns", headers=key).json()["data"]) == 2
    running = api.get("/v1/campaigns?status=running", headers=key).json()["data"]
    assert [c["name"] for c in running] == ["Diwali"]
    assert api.get(f"/v1/campaigns/{running[0]['id']}", headers=key).json()["status"] == "running"


def test_a_lead_posted_to_an_instant_employee_is_accepted_deduplicated_or_rejected(
    api: TestClient, migrated_url: str
) -> None:
    owner, key, employee = setup(api, migrated_url)
    url = f"/v1/employees/{employee}/leads"
    accepted = api.post(
        url, json={"phone": "98765 43210", "name": "Asha", "budget": "1cr"}, headers=key
    )
    assert accepted.status_code == 202 and accepted.json()["status"] == "accepted"
    assert accepted.json()["call_id"] and accepted.json()["lead_id"]
    queued = sql(
        migrated_url, "SELECT status FROM calls WHERE id = :i", {"i": accepted.json()["call_id"]}
    )
    assert queued == "queued"
    log = sql(migrated_url, "SELECT source FROM lead_intake_log WHERE status = 'accepted'")
    assert log == "api"

    again = api.post(url, json={"phone": CALLER}, headers=key)
    assert again.status_code == 200 and again.json()["status"] == "deduplicated"
    bad = api.post(url, json={"name": "no phone"}, headers=key)
    assert bad.status_code == 422 and bad.json()["status"] == "rejected"
    assert api.post(url, json=["phone"], headers=key).status_code == 422
    assert (
        api.post(
            f"/v1/employees/{uuid.uuid4()}/leads", json={"phone": CALLER}, headers=key
        ).status_code
        == 404
    )

    bulk = live_employee(api, migrated_url, owner, number="+911400000005", channel="bulk")
    refused = api.post(f"/v1/employees/{bulk}/leads", json={"phone": "+919876543299"}, headers=key)
    assert refused.status_code == 422 and "not on the Instant channel" in refused.json()["reason"]

    other = signup(api, email="b@example.com", account="Other")
    foreign = bearer(make_key(api, other))
    assert api.post(url, json={"phone": "+919876543288"}, headers=foreign).status_code == 404


@pytest.fixture
def limited_api(monkeypatch: pytest.MonkeyPatch) -> None:
    url = os.environ.get("AXON_TEST_REDIS_URL")
    if not url:
        pytest.skip("AXON_TEST_REDIS_URL not set; the rate limit needs a real Redis")
    monkeypatch.setenv("REDIS_URL", url)
    monkeypatch.setattr(keys, "LIMIT_PER_MINUTE", 3)


def test_a_key_over_its_allowance_gets_429_and_another_key_does_not(
    limited_api: None, api: TestClient
) -> None:
    owner = signup(api)
    busy, calm = make_key(api, owner), make_key(api, owner, "calm")
    codes = [api.get("/v1/account", headers=bearer(busy)).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    over = api.get("/v1/account", headers=bearer(busy))
    assert 1 <= int(over.headers["retry-after"]) <= 60
    assert api.get("/v1/account", headers=bearer(calm)).status_code == 200
