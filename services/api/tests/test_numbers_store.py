"""The number store: search, quote, buy, give back; always at our price, scoped to the account."""

import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.auth import issue_token
from app.models import User
from app.numbers.renewals import next_month, today_ist

from .conftest import sql
from .helpers import account_id, give_credits, seed, signup, verified_holder
from .vobiz_fake import ACCOUNT, VobizAccount

REGULAR, SERIES_140, SERIES_1600 = "+919100000001", "+911400000042", "+911600000042"


@pytest.fixture
def api(db_client: TestClient, migrated_url: str) -> TestClient:
    seed(migrated_url)
    return db_client


def ready(api: TestClient, url: str, credits: str = "1000") -> tuple[dict[str, str], str]:
    """An owner with credits and a verified holder."""
    owner = signup(api)
    mine = account_id(api, owner)
    give_credits(url, mine, credits)
    verified_holder(url, mine)
    return owner, mine


def balance(api: TestClient, owner: dict[str, str]) -> Decimal:
    return Decimal(api.get("/wallet", headers=owner).json()["balance"])


def test_inventory_is_searched_at_the_carrier_and_priced_by_us(
    api: TestClient, vobiz: VobizAccount
) -> None:
    owner = signup(api)
    got = api.get("/numbers/inventory?search=00000&per_page=50", headers=owner).json()
    assert [(n["e164"], n["number_type"]) for n in got] == [
        (REGULAR, "regular"),
        ("+919100000002", "regular"),
        (SERIES_140, "140"),
        (SERIES_1600, "1600"),
    ]
    assert {(n["monthly_fee"], n["setup_fee"]) for n in got} == {("649", "0")}  # not the carrier's
    request = vobiz.requests[0]
    assert request.method == "GET"
    assert str(request.url) == (
        "https://api.vobiz.ai/api/v1/Account/MA_TEST/inventory/numbers"
        "?country=IN&search=00000&page=1&per_page=50"
    )
    assert request.headers["X-Auth-ID"] == "MA_TEST" and request.headers["X-Auth-Token"] == "token"
    assert api.get("/numbers/inventory?search=abc", headers=owner).status_code == 422
    assert api.get("/numbers/inventory?per_page=101", headers=owner).status_code == 422
    assert api.get("/numbers/inventory").status_code == 401


def test_a_quote_says_what_the_first_charge_is_and_whether_kyc_is_needed(
    api: TestClient, migrated_url: str, vobiz: VobizAccount
) -> None:
    owner = signup(api)
    quote = api.get("/numbers/quote", params={"e164": SERIES_140}, headers=owner).json()
    assert quote == {
        "e164": SERIES_140,
        "number_type": "140",
        "setup_fee": "0",
        "monthly_fee": "649",
        "first_charge": "649.0000",
        "balance": "50.0000",
        "kyc_required": True,
    }
    mine = account_id(api, owner)
    verified_holder(migrated_url, mine)
    assert (
        api.get("/numbers/quote", params={"e164": SERIES_140}, headers=owner).json()["kyc_required"]
        is False
    )
    assert (
        api.get("/numbers/quote", params={"e164": "+919999999999"}, headers=owner).status_code
        == 404
    )
    assert api.get("/numbers/quote?e164=12", headers=owner).status_code == 422


def test_buying_needs_a_verified_holder_and_credits_before_anything_is_spent(
    api: TestClient, migrated_url: str, vobiz: VobizAccount
) -> None:
    owner = signup(api)
    give_credits(migrated_url, account_id(api, owner), "1000")
    got = api.post("/numbers/purchase", json={"e164": REGULAR}, headers=owner)
    assert got.status_code == 409 and "verify the number holder" in got.json()["detail"]
    sql(
        migrated_url,
        "INSERT INTO kyc_holders (account_id, name, status) VALUES (:a, 'X', 'pan_verified')",
        {"a": account_id(api, owner)},
    )
    assert api.post("/numbers/purchase", json={"e164": REGULAR}, headers=owner).status_code == 409
    poor = signup(api, "b@example.com", "B")
    verified_holder(migrated_url, account_id(api, poor))
    refused = api.post("/numbers/purchase", json={"e164": REGULAR}, headers=poor)
    assert refused.status_code == 402 and refused.json()["error"] == "insufficient_credits"
    assert vobiz.sent("POST", "/numbers") == [] and vobiz.owned == set()
    assert balance(api, poor) == 50 and balance(api, owner) == 1050


def test_a_purchase_debits_the_wallet_then_buys_and_starts_the_rental(
    api: TestClient, migrated_url: str, vobiz: VobizAccount
) -> None:
    owner, _ = ready(api, migrated_url)
    got = api.post("/numbers/purchase", json={"e164": SERIES_140}, headers=owner)
    assert got.status_code == 201, got.text
    number = got.json()
    expected_renewal = next_month(today_ist(datetime.now(UTC)))
    assert (number["e164"], number["number_type"], number["status"], number["channels"]) == (
        SERIES_140, "140", "active", 1,
    )  # fmt: skip
    assert number["monthly_fee"] == "649.0000" and number["renews_on"] == str(expected_renewal)
    bought = vobiz.sent("POST", "/numbers/purchase-from-inventory")
    assert len(bought) == 1
    assert json.loads(bought[0].content) == {"e164": SERIES_140, "currency": "INR"}
    assert balance(api, owner) == Decimal(1050 - 649)
    row = sql(
        migrated_url,
        "SELECT kind::text || amount::text FROM wallet_ledger WHERE kind = 'number'",
    )
    assert row == "number-649.0000"
    holder = sql(migrated_url, "SELECT holder_id FROM numbers WHERE e164 = :e", {"e": SERIES_140})
    assert holder is not None
    assert sql(migrated_url, "SELECT provider_ref FROM numbers") == "num_0042"
    assert [n["e164"] for n in api.get("/numbers", headers=owner).json()] == [SERIES_140]


def test_a_carrier_refusal_gives_the_credits_back_and_keeps_no_number(
    api: TestClient, migrated_url: str, vobiz: VobizAccount
) -> None:
    owner, _ = ready(api, migrated_url)
    vobiz.fail_buy = True
    got = api.post("/numbers/purchase", json={"e164": REGULAR}, headers=owner)
    assert got.status_code == 502
    assert balance(api, owner) == 1050
    kinds = sql(migrated_url, "SELECT string_agg(kind::text, ',' ORDER BY id) FROM wallet_ledger")
    assert kinds == "bonus,topup,number,refund"
    assert sql(migrated_url, "SELECT count(*) FROM numbers") == 0
    vobiz.fail_buy = False
    assert api.post("/numbers/purchase", json={"e164": REGULAR}, headers=owner).status_code == 201


def test_a_number_someone_holds_cannot_be_bought_again(
    api: TestClient, migrated_url: str, vobiz: VobizAccount
) -> None:
    first, _ = ready(api, migrated_url)
    other = signup(api, "b@example.com", "B")
    give_credits(migrated_url, account_id(api, other), "1000")
    verified_holder(migrated_url, account_id(api, other))
    assert api.post("/numbers/purchase", json={"e164": REGULAR}, headers=first).status_code == 201
    again = api.post("/numbers/purchase", json={"e164": REGULAR}, headers=other)
    assert again.status_code == 409 and "taken" in again.json()["detail"]
    assert balance(api, other) == 1050


def test_releasing_gives_the_number_back_and_is_scoped(
    api: TestClient, migrated_url: str, vobiz: VobizAccount
) -> None:
    owner, _ = ready(api, migrated_url, "2000")
    other = signup(api, "b@example.com", "B")
    number = api.post("/numbers/purchase", json={"e164": REGULAR}, headers=owner).json()["id"]
    assert api.delete(f"/numbers/{number}", headers=other).status_code == 404
    assert vobiz.sent("DELETE", "/numbers") == []
    got = api.delete(f"/numbers/{number}", headers=owner)
    assert got.status_code == 200 and got.json() == {"status": "released"}
    released = vobiz.sent("DELETE", "/numbers")
    assert [r.url.raw_path.decode() for r in released] == [f"{ACCOUNT}/numbers/%2B919100000001"]
    assert api.delete(f"/numbers/{number}", headers=owner).status_code == 409
    assert api.get("/numbers", headers=owner).json() == []
    assert balance(api, owner) == Decimal(2050 - 649)  # rent already paid is not refunded
    assert api.post("/numbers/purchase", json={"e164": REGULAR}, headers=owner).status_code == 201


def test_numbers_are_listed_for_the_account_only_and_buying_is_owner_only(
    api: TestClient, migrated_url: str, vobiz: VobizAccount
) -> None:
    owner, mine = ready(api, migrated_url)
    other = signup(api, "b@example.com", "B")
    api.post("/numbers/purchase", json={"e164": REGULAR}, headers=owner)
    assert api.get("/numbers", headers=other).json() == []
    member_id = sql(
        migrated_url,
        "INSERT INTO users (account_id, email, password_hash, role)"
        " VALUES (:a, 'm@example.com', 'x', 'member') RETURNING id",
        {"a": mine},
    )
    member = {"Authorization": f"Bearer {issue_token(User(id=member_id))}"}
    assert len(api.get("/numbers", headers=member).json()) == 1
    assert (
        api.post("/numbers/purchase", json={"e164": SERIES_140}, headers=member).status_code == 403
    )


def test_every_store_route_is_503_without_carrier_keys(api: TestClient, migrated_url: str) -> None:
    owner, mine = ready(api, migrated_url)
    number = sql(
        migrated_url,
        "INSERT INTO numbers (account_id, provider, e164, number_type, status)"
        " VALUES (:a, 'vobiz', '+919100000009', 'regular', 'active') RETURNING id",
        {"a": mine},
    )
    for response in (
        api.get("/numbers/inventory", headers=owner),
        api.get("/numbers/quote", params={"e164": REGULAR}, headers=owner),
        api.post("/numbers/purchase", json={"e164": REGULAR}, headers=owner),
        api.delete(f"/numbers/{number}", headers=owner),
    ):
        assert response.status_code == 503 and response.json()["error"] == "provider_not_configured"
        assert response.json()["missing_keys"] == ["VOBIZ_AUTH_ID", "VOBIZ_AUTH_TOKEN"]
    assert balance(api, owner) == 1050 and sql(migrated_url, "SELECT count(*) FROM numbers") == 1
