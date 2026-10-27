"""Number KYC: PAN, then Aadhaar through DigiLocker; the verified holder is reused."""

import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.auth import issue_token
from app.models import User

from .conftest import sql
from .helpers import account_id, give_credits, seed, signup
from .vobiz_fake import GOOD_PAN, VobizAccount

NAME = "Asha Rao"


@pytest.fixture
def api(db_client: TestClient, migrated_url: str) -> TestClient:
    seed(migrated_url)
    return db_client


def pan_step(
    api: TestClient, owner: dict[str, str], pan: str = GOOD_PAN, name: str = NAME
) -> dict[str, str]:
    got = api.post("/numbers/kyc/verify-pan", json={"name": name, "pan": pan}, headers=owner)
    assert got.status_code == 201, got.text
    holder: dict[str, str] = got.json()
    return holder


def finish(api: TestClient, owner: dict[str, str], vobiz: VobizAccount) -> str:
    """Both steps; returns the holder id."""
    holder = pan_step(api, owner)
    started = api.post(
        "/numbers/kyc/digilocker/initiate",
        json={"holder_id": holder["id"], "redirect_url": "https://app.example.in/kyc"},
        headers=owner,
    )
    assert started.status_code == 200
    vobiz.consent_given = True
    done = api.post(
        "/numbers/kyc/digilocker/verify", json={"holder_id": holder["id"]}, headers=owner
    )
    assert done.status_code == 200 and done.json()["status"] == "verified"
    return holder["id"]


def test_pan_is_checked_against_the_name_and_only_its_last_four_are_kept(
    api: TestClient, migrated_url: str, vobiz: VobizAccount, caplog: pytest.LogCaptureFixture
) -> None:
    owner = signup(api)
    with caplog.at_level(logging.DEBUG):
        got = api.post(
            "/numbers/kyc/verify-pan", json={"name": NAME, "pan": GOOD_PAN.lower()}, headers=owner
        )
    assert got.status_code == 201
    holder = got.json()
    assert (holder["name"], holder["pan_last4"], holder["status"]) == (
        "ASHA RAO",
        "234F",
        "pan_verified",
    )
    assert GOOD_PAN not in got.text and GOOD_PAN not in caplog.text
    sent = vobiz.sent("POST", "/kyc/pan")
    assert len(sent) == 1 and json.loads(sent[0].content) == {"pan": GOOD_PAN, "name": NAME}
    # Nowhere in the database: every table, every column, as text.
    tables = [
        str(t)
        for t in sql(
            migrated_url, "SELECT array_agg(tablename) FROM pg_tables WHERE schemaname = 'public'"
        )
    ]
    for table in tables:
        hits = sql(
            migrated_url,
            f'SELECT count(*) FROM "{table}" t WHERE t::text LIKE :p',  # noqa: S608
            {"p": f"%{GOOD_PAN}%"},
        )
        assert hits == 0, table


def test_a_pan_that_does_not_match_or_is_malformed_makes_no_holder(
    api: TestClient, migrated_url: str, vobiz: VobizAccount
) -> None:
    owner = signup(api)
    wrong = api.post(
        "/numbers/kyc/verify-pan", json={"name": NAME, "pan": "ZZZZZ9999Z"}, headers=owner
    )
    assert wrong.status_code == 422 and "does not match" in wrong.json()["detail"]
    for pan in ("abc", "ABCDE12345", "ABCD1234FF", ""):
        bad = api.post("/numbers/kyc/verify-pan", json={"name": NAME, "pan": pan}, headers=owner)
        assert bad.status_code == 422, pan
    assert (
        api.post(
            "/numbers/kyc/verify-pan", json={"name": "A", "pan": GOOD_PAN}, headers=owner
        ).status_code
        == 422
    )
    assert sql(migrated_url, "SELECT count(*) FROM kyc_holders") == 0
    assert len(vobiz.sent("POST", "/kyc/pan")) == 1  # only the well-formed one reached the carrier


def test_aadhaar_comes_second_and_needs_the_holders_consent(
    api: TestClient, vobiz: VobizAccount
) -> None:
    owner = signup(api)
    holder = pan_step(api, owner)
    early = api.post(
        "/numbers/kyc/digilocker/verify", json={"holder_id": holder["id"]}, headers=owner
    )
    assert early.status_code == 409  # DigiLocker was never started
    redirect = {"holder_id": holder["id"], "redirect_url": "http://app.example.in/kyc"}
    assert (
        api.post("/numbers/kyc/digilocker/initiate", json=redirect, headers=owner).status_code
        == 422
    )
    redirect["redirect_url"] = "https://app.example.in/kyc"
    started = api.post("/numbers/kyc/digilocker/initiate", json=redirect, headers=owner)
    assert started.json() == {"url": "https://digilocker.example/consent?s=1"}
    sent = vobiz.sent("POST", "/kyc/digilocker/initiate")
    assert json.loads(sent[0].content) == {
        "holder_id": "h_1",
        "redirect_url": "https://app.example.in/kyc",
    }
    waiting = api.post(
        "/numbers/kyc/digilocker/verify", json={"holder_id": holder["id"]}, headers=owner
    )
    assert waiting.status_code == 409 and "not finished" in waiting.json()["detail"]
    assert api.get("/numbers/holders", headers=owner).json()[0]["status"] == "pan_verified"
    vobiz.consent_given = True
    done = api.post(
        "/numbers/kyc/digilocker/verify", json={"holder_id": holder["id"]}, headers=owner
    )
    assert done.json()["status"] == "verified"
    again = api.post(
        "/numbers/kyc/digilocker/verify", json={"holder_id": holder["id"]}, headers=owner
    )
    assert again.status_code == 200  # asking twice is harmless


def test_digilocker_cannot_start_before_the_pan_is_verified(
    api: TestClient, migrated_url: str, vobiz: VobizAccount
) -> None:
    owner = signup(api)
    pending = sql(
        migrated_url,
        "INSERT INTO kyc_holders (account_id, name, status) VALUES (:a, 'X', 'new') RETURNING id",
        {"a": account_id(api, owner)},
    )
    body = {"holder_id": str(pending), "redirect_url": "https://app.example.in/kyc"}
    assert api.post("/numbers/kyc/digilocker/initiate", json=body, headers=owner).status_code == 409
    assert vobiz.sent("POST", "/kyc") == []


def test_holders_belong_to_their_account(api: TestClient, vobiz: VobizAccount) -> None:
    mine, theirs = signup(api), signup(api, "b@example.com", "B")
    holder = pan_step(api, mine)
    assert api.get("/numbers/holders", headers=theirs).json() == []
    body = {"holder_id": holder["id"], "redirect_url": "https://app.example.in/kyc"}
    assert (
        api.post("/numbers/kyc/digilocker/initiate", json=body, headers=theirs).status_code == 404
    )
    verify = api.post(
        "/numbers/kyc/digilocker/verify", json={"holder_id": holder["id"]}, headers=theirs
    )
    assert verify.status_code == 404


def test_one_verified_holder_serves_every_later_number(
    api: TestClient, migrated_url: str, vobiz: VobizAccount
) -> None:
    owner = signup(api)
    give_credits(migrated_url, account_id(api, owner), "2000")
    holder = finish(api, owner, vobiz)
    kyc_calls = len([r for r in vobiz.requests if "/kyc/" in r.url.path])
    for e164 in ("+919100000001", "+919100000002"):
        assert api.post("/numbers/purchase", json={"e164": e164}, headers=owner).status_code == 201
    holders = sql(migrated_url, "SELECT count(DISTINCT holder_id) || ',' || count(*) FROM numbers")
    assert holders == "1,2"
    assert str(sql(migrated_url, "SELECT holder_id FROM numbers LIMIT 1")) == holder
    assert len([r for r in vobiz.requests if "/kyc/" in r.url.path]) == kyc_calls  # no new checks
    assert sql(migrated_url, "SELECT count(*) FROM kyc_holders") == 1


def test_a_holder_who_stopped_after_the_pan_cannot_buy(
    api: TestClient, migrated_url: str, vobiz: VobizAccount
) -> None:
    owner = signup(api)
    give_credits(migrated_url, account_id(api, owner), "2000")
    pan_step(api, owner)
    got = api.post("/numbers/purchase", json={"e164": "+919100000001"}, headers=owner)
    assert got.status_code == 409 and vobiz.sent("POST", "/numbers") == []


def test_kyc_routes_are_503_without_keys_and_owner_only(
    api: TestClient, migrated_url: str, vobiz: VobizAccount
) -> None:
    owner = signup(api)
    member_id = sql(
        migrated_url,
        "INSERT INTO users (account_id, email, password_hash, role)"
        " VALUES (:a, 'm@example.com', 'x', 'member') RETURNING id",
        {"a": account_id(api, owner)},
    )
    member = {"Authorization": f"Bearer {issue_token(User(id=member_id))}"}
    body = {"name": NAME, "pan": GOOD_PAN}
    assert api.post("/numbers/kyc/verify-pan", json=body, headers=member).status_code == 403
    assert vobiz.requests == []


def test_kyc_is_503_when_the_carrier_keys_are_missing(api: TestClient) -> None:
    owner = signup(api)
    got = api.post("/numbers/kyc/verify-pan", json={"name": NAME, "pan": GOOD_PAN}, headers=owner)
    assert got.status_code == 503 and got.json()["kind"] == "number_kyc"
    assert got.json()["missing_keys"] == ["VOBIZ_AUTH_ID", "VOBIZ_AUTH_TOKEN"]
