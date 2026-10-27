"""Statements, the running-balance list, per-employee usage and GST invoices."""

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.billing import invoices, payments
from app.billing.router import month_bounds

from .conftest import sql
from .helpers import account_id, add_call, live_employee, run_db, seed, signup

SELLER = {
    "AXON_SELLER_NAME": "ALTERX Pvt Ltd",
    "AXON_SELLER_GSTIN": "36AAAAA0000A1Z5",
    "AXON_SELLER_ADDRESS": "Hyderabad",
    "AXON_SELLER_STATE_CODE": "36",
    "AXON_GST_RATE": "18",
    "AXON_GST_SAC": "998439",
    "AXON_INVOICE_PREFIX": "AXN",
}


@pytest.fixture
def api(db_client: TestClient, migrated_url: str) -> TestClient:
    seed(migrated_url)
    return db_client


@pytest.fixture
def seller(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in SELLER.items():
        monkeypatch.setenv(key, value)


def entry(url: str, account: str, kind: str, amount: str, at: datetime, balance: str) -> None:
    sql(
        url,
        "INSERT INTO wallet_ledger (account_id, kind, amount, balance_after, created_at)"
        " VALUES (:a, :k, :x, :b, :t)",
        {"a": account, "k": kind, "x": Decimal(amount), "b": Decimal(balance), "t": at},
    )


# --- Statement and transactions ----------------------------------------------------------------


def test_the_indian_month_runs_from_midnight_to_midnight_ist() -> None:
    start, end = month_bounds("2026-11")
    assert start == datetime(2026, 10, 31, 18, 30, tzinfo=UTC)
    assert end == datetime(2026, 11, 30, 18, 30, tzinfo=UTC)
    assert month_bounds("2026-12")[1] == datetime(2026, 12, 31, 18, 30, tzinfo=UTC)


def test_a_statement_is_opening_balance_plus_movements_equals_closing(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    mine = account_id(api, owner)
    sql(migrated_url, "DELETE FROM wallet_ledger WHERE account_id = :a", {"a": mine})
    october = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
    entry(migrated_url, mine, "topup", "500", october, "500")
    # 00:10 IST on 1 November is still 18:40 UTC on 31 October: it belongs to November.
    entry(migrated_url, mine, "call", "-12.5", datetime(2026, 10, 31, 18, 40, tzinfo=UTC), "487.5")
    entry(migrated_url, mine, "number", "-649", datetime(2026, 11, 3, 5, 0, tzinfo=UTC), "-161.5")
    entry(migrated_url, mine, "topup", "1000", datetime(2026, 11, 9, 5, 0, tzinfo=UTC), "838.5")
    entry(migrated_url, mine, "call", "-8", datetime(2026, 11, 30, 18, 20, tzinfo=UTC), "830.5")
    entry(migrated_url, mine, "call", "-2", datetime(2026, 11, 30, 18, 40, tzinfo=UTC), "828.5")
    nov = api.get("/billing/statement?month=2026-11", headers=owner).json()
    assert nov["month"] == "2026-11"
    assert (nov["opening_balance"], nov["closing_balance"]) == ("500.0000", "830.5000")
    assert nov["by_kind"] == {
        "call": {"total": "-20.5000", "entries": 2},
        "number": {"total": "-649.0000", "entries": 1},
        "topup": {"total": "1000.0000", "entries": 1},
    }
    moved = sum(Decimal(v["total"]) for v in nov["by_kind"].values())
    assert Decimal(nov["opening_balance"]) + moved == Decimal(nov["closing_balance"])
    dec = api.get("/billing/statement?month=2026-12", headers=owner).json()
    assert (dec["opening_balance"], dec["closing_balance"]) == ("830.5000", "828.5000")
    assert dec["by_kind"] == {"call": {"total": "-2.0000", "entries": 1}}  # 00:10 IST on 1 Dec
    before = api.get("/billing/statement?month=2025-01", headers=owner).json()
    assert before["opening_balance"] == before["closing_balance"] == "0"


def test_this_and_last_month_are_named_and_the_signup_bonus_is_in_this_month(
    api: TestClient,
) -> None:
    owner = signup(api)
    now = datetime.now(UTC) + timedelta(hours=5, minutes=30)
    this = api.get("/billing/statement", headers=owner).json()
    assert this["month"] == now.strftime("%Y-%m") and this["by_kind"]["bonus"]["total"] == "50.0000"
    last = api.get("/billing/statement?month=last", headers=owner).json()
    assert last["month"] < this["month"] and last["by_kind"] == {}
    assert api.get("/billing/statement?month=2026-13", headers=owner).status_code == 422
    assert api.get("/billing/statement?month=soon", headers=owner).status_code == 422
    assert api.get("/billing/statement").status_code == 401


def test_transactions_carry_a_running_balance_and_page_back(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    mine = account_id(api, owner)
    rng = random.Random(7)  # noqa: S311 - a repeatable test sequence
    start = datetime(2026, 11, 1, tzinfo=UTC)
    running = Decimal(50)
    for step in range(30):
        amount = Decimal(rng.randint(-2000, 2000)) / 100
        running += amount
        kind = "topup" if amount > 0 else "call"
        entry(migrated_url, mine, kind, str(amount), start + timedelta(minutes=step), str(running))
    seen: list[dict[str, Any]] = []
    page = api.get("/billing/transactions?limit=12", headers=owner).json()["items"]
    while page:
        seen += page
        page = api.get(
            f"/billing/transactions?limit=12&before={page[-1]['id']}", headers=owner
        ).json()["items"]
    assert len(seen) == 31  # thirty, and the signup bonus
    oldest_first = list(reversed(seen))
    total = Decimal(0)
    for item in oldest_first:
        total += Decimal(item["amount"])
        assert Decimal(item["balance_after"]) == total  # each line carries the balance so far
    assert sorted(item["id"] for item in seen) == [item["id"] for item in reversed(seen)]
    assert api.get("/billing/transactions?limit=0", headers=owner).status_code == 422


def test_statements_and_transactions_only_show_my_account(
    api: TestClient, migrated_url: str
) -> None:
    mine, theirs = signup(api), signup(api, "b@example.com", "B")
    entry(migrated_url, account_id(api, theirs), "topup", "9999", datetime.now(UTC), "10049")
    ids = [t["id"] for t in api.get("/billing/transactions", headers=mine).json()["items"]]
    assert len(ids) == 1  # only my signup bonus
    assert api.get("/billing/statement", headers=mine).json()["by_kind"] == {
        "bonus": {"total": "50.0000", "entries": 1}
    }


# --- Usage -------------------------------------------------------------------------------------


def test_usage_adds_up_billed_calls_per_employee_for_the_month(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    mine = sql(migrated_url, "SELECT id FROM accounts")
    asha = live_employee(api, migrated_url, owner, number="+911400000001")
    ravi = live_employee(api, migrated_url, owner, number="+911400000002")
    ended = datetime(2026, 11, 10, 6, 0, tzinfo=UTC)

    def billed(employee: str, seconds: int, credits: str, when: datetime = ended) -> None:
        call = add_call(migrated_url, mine, employee, ended_at=when)
        sql(
            migrated_url,
            "UPDATE calls SET billing_status = 'billed', billed_seconds = :s, credits_charged = :c"
            " WHERE id = :i",
            {"s": seconds, "c": Decimal(credits), "i": call},
        )

    billed(asha, 60, "3.5")
    billed(asha, 30, "1.75")
    billed(ravi, 120, "14")
    billed(ravi, 600, "70", datetime(2026, 12, 2, 6, 0, tzinfo=UTC))  # another month
    free = add_call(migrated_url, mine, ravi, ended_at=ended)  # answered by nobody: not billed
    sql(migrated_url, "UPDATE calls SET billing_status = 'free' WHERE id = :i", {"i": free})
    got = api.get("/billing/usage?month=2026-11", headers=owner).json()["employees"]
    assert [(e["employee_id"], e["calls"], e["talk_seconds"], e["credits"]) for e in got] == [
        (ravi, 1, 120, "14.0000"),
        (asha, 2, 90, "5.2500"),
    ]
    assert {e["name"] for e in got} == {"Asha"}
    assert (
        api.get("/billing/usage?month=2026-12", headers=owner).json()["employees"][0]["credits"]
        == "70.0000"
    )
    other = signup(api, "b@example.com", "B")
    assert api.get("/billing/usage?month=2026-11", headers=other).json()["employees"] == []


# --- GST invoices ------------------------------------------------------------------------------


def paid(url: str, account: str, amount: str, order: str, at: datetime) -> str:
    payment = sql(
        url,
        "INSERT INTO payments (account_id, provider, provider_order_id, amount_inr, status)"
        " VALUES (:a, 'razorpay', :o, :x, 'created') RETURNING id",
        {"a": account, "o": order, "x": Decimal(amount)},
    )

    async def work(factory: Any) -> None:
        async with factory() as session:
            await payments.settle(session, order, f"pay_{order}", now=at)
            await session.commit()

    run_db(url, work)
    return str(payment)


@pytest.mark.parametrize("total", ["100", "118", "500", "1000", "2499.99", "100000", "100.01"])
def test_tax_parts_always_add_up_to_what_was_paid(total: str) -> None:
    for same_state in (True, False):
        parts = invoices.split_tax(Decimal(total), Decimal(18), same_state=same_state)
        assert parts["taxable"] + parts["cgst"] + parts["sgst"] + parts["igst"] == Decimal(total)
        assert (parts["igst"] == 0) == same_state
        assert parts["cgst"] == parts["sgst"] or abs(parts["cgst"] - parts["sgst"]) == Decimal(
            "0.01"
        )
    assert invoices.split_tax(Decimal(118), Decimal(18), same_state=True) == {
        "taxable": Decimal("100.00"),
        "cgst": Decimal("9.00"),
        "sgst": Decimal("9.00"),
        "igst": Decimal("0.00"),
    }


def test_a_same_state_buyer_pays_cgst_plus_sgst_and_another_state_pays_igst(
    api: TestClient, migrated_url: str, seller: None
) -> None:
    local, remote = signup(api), signup(api, "b@example.com", "B")
    for headers, state in ((local, "36"), (remote, "29")):
        got = api.put(
            "/billing/settings",
            json={"legal_name": "Buyer", "state_code": state, "gstin": f"{state}BBBBB1111B1Z6"},
            headers=headers,
        )
        assert got.status_code == 200, got.text
    at = datetime(2026, 11, 10, 6, 0, tzinfo=UTC)
    paid(migrated_url, account_id(api, local), "1180", "order_a", at)
    paid(migrated_url, account_id(api, remote), "1180", "order_b", at)
    a = api.get("/billing/invoices", headers=local).json()[0]
    assert (a["taxable"], a["cgst"], a["sgst"], a["igst"], a["total"]) == (
        "1000.00", "90.00", "90.00", "0.00", "1180.00",
    )  # fmt: skip
    b = api.get("/billing/invoices", headers=remote).json()[0]
    assert (b["taxable"], b["cgst"], b["sgst"], b["igst"]) == ("1000.00", "0.00", "0.00", "180.00")
    assert a["seller"]["gstin"] == "36AAAAA0000A1Z5" and a["sac_code"] == "998439"
    assert a["gst_rate_percent"] == "18" and a["buyer"]["state_code"] == "36"
    assert b["place_of_supply"] == "29"


def test_rate_and_codes_come_from_configuration_and_stay_as_issued(
    api: TestClient, migrated_url: str, seller: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = signup(api)
    mine = account_id(api, owner)
    monkeypatch.setenv("AXON_GST_RATE", "12")
    monkeypatch.setenv("AXON_GST_SAC", "123456")
    paid(migrated_url, mine, "1120", "order_a", datetime(2026, 11, 10, tzinfo=UTC))
    monkeypatch.setenv("AXON_GST_RATE", "5")  # changed later: the issued invoice keeps its own
    first = api.get("/billing/invoices", headers=owner).json()[0]
    assert (first["taxable"], first["gst_rate_percent"], first["sac_code"]) == (
        "1000.00",
        "12",
        "123456",
    )
    assert first["buyer"] == {"legal_name": "Acme"}  # no state given: treated as the seller's state
    assert (first["cgst"], first["sgst"]) == ("60.00", "60.00")


def test_invoice_numbers_run_in_order_without_gaps_and_restart_each_financial_year(
    api: TestClient, migrated_url: str, seller: None
) -> None:
    owner = signup(api)
    mine = account_id(api, owner)
    stamps = [
        datetime(2026, 3, 31, 18, 29, tzinfo=UTC),  # 23:59 IST on 31 March: still 2025-26
        datetime(2026, 3, 31, 18, 31, tzinfo=UTC),  # 00:01 IST on 1 April: 2026-27
        datetime(2026, 11, 10, tzinfo=UTC),
        datetime(2027, 3, 31, 19, 0, tzinfo=UTC),  # 00:30 IST on 1 April 2027: 2027-28
    ]
    for index, at in enumerate(stamps):
        paid(migrated_url, mine, "500", f"order_{index}", at)
    numbers = sorted(i["number"] for i in api.get("/billing/invoices", headers=owner).json())
    assert numbers == [
        "AXN/2025-26/000001",
        "AXN/2026-27/000001",
        "AXN/2026-27/000002",
        "AXN/2027-28/000001",
    ]
    assert invoices.financial_year(datetime(2026, 4, 1, 0, 0, tzinfo=UTC)) == "2026-27"


def test_invoices_are_scoped_to_the_account(
    api: TestClient, migrated_url: str, seller: None
) -> None:
    mine, theirs = signup(api), signup(api, "b@example.com", "B")
    paid(migrated_url, account_id(api, mine), "500", "order_a", datetime(2026, 11, 10, tzinfo=UTC))
    invoice = api.get("/billing/invoices", headers=mine).json()[0]
    assert (
        api.get(f"/billing/invoices/{invoice['id']}", headers=mine).json()["number"]
        == invoice["number"]
    )
    assert api.get(f"/billing/invoices/{invoice['id']}", headers=theirs).status_code == 404
    assert api.get("/billing/invoices", headers=theirs).json() == []
    assert api.get(f"/billing/invoices/{invoice['id']}").status_code == 401


def test_invoice_details_are_checked_before_they_are_kept(api: TestClient) -> None:
    owner = signup(api)
    assert (
        api.put("/billing/settings", json={"gstin": "nonsense"}, headers=owner).status_code == 422
    )
    clash = {"gstin": "36AAAAA0000A1Z5", "state_code": "29"}
    assert api.put("/billing/settings", json=clash, headers=owner).status_code == 422
    assert api.put("/billing/settings", json={"state_code": "9"}, headers=owner).status_code == 422
    ok = api.put("/billing/settings", json={"gstin": "36aaaaa0000a1z5"}, headers=owner)
    assert ok.json()["details"] == {"gstin": "36AAAAA0000A1Z5"}
    cleared = api.put("/billing/settings", json={"gstin": ""}, headers=owner)
    assert cleared.json()["details"] == {}
