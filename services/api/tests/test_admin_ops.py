"""Admin console: the voice library, vendor health, costs and balances, and the carrier."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.billing import ledger
from app.models import LedgerKind
from app.providers import health

from .conftest import sql
from .helpers import account_id, add_call, live_employee, run_db, seed, signup, staff

VOICE = {
    "provider": "sarvam",
    "provider_voice_id": "meera",
    "name": "Meera",
    "native_language": "te",
    "accent": "Hyderabad",
    "tone_tags": ["warm"],
    "language_scores": {"te": 0.95, "en": 0.7},
}


@pytest.fixture
def admin(db_client: TestClient, migrated_url: str) -> dict[str, str]:
    return staff(db_client, migrated_url)


def test_the_voice_library_is_kept_by_staff(
    db_client: TestClient, migrated_url: str, admin: dict[str, str]
) -> None:
    made = db_client.post("/admin/voices", json=VOICE, headers=admin)
    assert made.status_code == 201
    voice = made.json()
    assert (voice["tier"], voice["languages"]) == ("value", ["en", "te"])  # Sarvam is Value
    owner = signup(db_client, email="owner@example.com")
    listed = db_client.get("/voices", params={"language": "te"}, headers=owner).json()
    assert [v["name"] for v in listed] == ["Meera"]

    again = db_client.post("/admin/voices", json=VOICE, headers=admin)
    assert again.status_code == 409  # one row per vendor voice
    premium = {**VOICE, "provider": "cartesia", "name": "Meera HD"}
    edited = db_client.put(f"/admin/voices/{voice['id']}", json=premium, headers=admin)
    assert edited.json()["tier"] == "premium" and edited.json()["name"] == "Meera HD"
    for bad in ({**VOICE, "provider": "acme"}, {**VOICE, "language_scores": {"te": 2}}):
        assert db_client.post("/admin/voices", json=bad, headers=admin).status_code == 422

    employee = db_client.post(
        "/employees",
        json={"channel": "instant", "name": "Asha", "voice_id": voice["id"]},
        headers=owner,
    ).json()
    in_use = db_client.delete(f"/admin/voices/{voice['id']}", headers=admin)
    assert in_use.status_code == 409 and "1 employee" in in_use.json()["detail"]
    sql(migrated_url, "UPDATE employees SET voice_id = NULL WHERE id = :e", {"e": employee["id"]})
    assert db_client.delete(f"/admin/voices/{voice['id']}", headers=admin).status_code == 204
    assert db_client.delete(f"/admin/voices/{voice['id']}", headers=admin).status_code == 404
    logged = "SELECT count(*) FROM audit_log WHERE action LIKE 'voice_%'"
    assert sql(migrated_url, logged) == 3


def test_provider_health_shows_the_live_score(
    db_client: TestClient, migrated_url: str, admin: dict[str, str]
) -> None:
    async def work(factory: Any) -> None:
        async with factory() as session:
            now = datetime.now(UTC)
            for ok in (False, False, False, True):
                health.record(session, "tts", "cartesia", ok=ok, at=now)
            health.record(session, "stt", "sarvam", ok=True, at=now)
            await session.commit()

    run_db(migrated_url, work)
    body = db_client.get("/admin/provider-health", headers=admin).json()
    rows = {(r["kind"], r["vendor"]): r for r in body["providers"]}
    assert rows[("tts", "cartesia")] == {
        "kind": "tts",
        "vendor": "cartesia",
        "ok": 1,
        "failed": 3,
        "success_rate": 0.25,
        "healthy": False,
    }
    assert rows[("stt", "sarvam")]["healthy"] and rows[("stt", "sarvam")]["success_rate"] == 1.0
    assert rows[("llm", "gemini")]["success_rate"] is None  # nothing seen yet
    probe = db_client.get("/admin/providers", headers=admin).json()["providers"]
    assert {(p["kind"], p["name"]) for p in probe} == set(rows)  # the probe covers the same vendors


def a_call_with_usage(url: str, account: Any, *, billed: int, ago: timedelta) -> None:
    number = sql(url, "SELECT id FROM numbers LIMIT 1")
    ended = datetime.now(UTC) - ago
    call = add_call(url, account, status="completed", ended_at=ended)
    sql(
        url,
        "UPDATE calls SET number_id = :n, billed_seconds = :b WHERE id = :c",
        {"n": number, "b": billed, "c": call},
    )
    meters = [
        {"kind": "stt", "vendor": "sarvam", "unit": "audio_seconds", "amount": 60.0},
        {"kind": "llm", "vendor": "gemini", "unit": "input_tokens", "amount": 1000},
        {"kind": "tts", "vendor": "sarvam", "unit": "characters", "amount": 500},
    ]
    sql(
        url,
        "INSERT INTO call_events (call_id, type, data, at)"
        " VALUES (:c, 'usage', CAST(:d AS jsonb), :at)",
        {"c": call, "d": json.dumps({"duration_s": 60, "meters": meters}), "at": ended},
    )


def test_provider_costs_are_metered_usage_at_the_entered_rates(
    db_client: TestClient, migrated_url: str, admin: dict[str, str]
) -> None:
    seed(migrated_url)
    owner = signup(db_client, email="owner@example.com")
    live_employee(db_client, migrated_url, owner)
    account = account_id(db_client, owner)
    a_call_with_usage(migrated_url, account, billed=60, ago=timedelta(hours=1))
    a_call_with_usage(migrated_url, account, billed=30, ago=timedelta(hours=2))
    a_call_with_usage(migrated_url, account, billed=600, ago=timedelta(days=40))  # outside

    rates = [
        ("stt", "sarvam", "audio_seconds", "0.005"),
        ("tts", "sarvam", "characters", "0.0003"),
        ("telephony", "vobiz", "seconds", "0.01"),
    ]
    for kind, vendor, unit, rate in rates:
        body = {"kind": kind, "vendor": vendor, "unit": unit, "inr_per_unit": rate}
        assert db_client.put("/admin/provider-rates", json=body, headers=admin).status_code == 200
    wrong = {"kind": "tts", "vendor": "acme", "unit": "characters", "inr_per_unit": "1"}
    assert db_client.put("/admin/provider-rates", json=wrong, headers=admin).status_code == 422
    assert len(db_client.get("/admin/provider-rates", headers=admin).json()) == 3

    body = db_client.get("/admin/provider-costs", params={"days": 30}, headers=admin).json()
    rows = {(r["kind"], r["vendor"], r["unit"]): r for r in body["items"]}
    assert Decimal(rows[("stt", "sarvam", "audio_seconds")]["usage"]) == 120
    assert Decimal(rows[("stt", "sarvam", "audio_seconds")]["cost_inr"]) == Decimal("0.60")
    assert Decimal(rows[("tts", "sarvam", "characters")]["cost_inr"]) == Decimal("0.30")
    assert Decimal(rows[("telephony", "vobiz", "seconds")]["usage"]) == 90
    assert Decimal(rows[("telephony", "vobiz", "seconds")]["cost_inr"]) == Decimal("0.90")
    gemini = rows[("llm", "gemini", "input_tokens")]
    assert Decimal(gemini["usage"]) == 2000 and gemini["cost_inr"] is None  # no rate: no guess
    assert body["unpriced"] == ["llm/gemini/input_tokens"]
    assert Decimal(body["total_inr"]) == Decimal("1.80")


def test_a_provider_balance_is_what_was_recorded_less_the_cost_since(
    db_client: TestClient, migrated_url: str, admin: dict[str, str]
) -> None:
    seed(migrated_url)
    owner = signup(db_client, email="owner@example.com")
    live_employee(db_client, migrated_url, owner)
    account = account_id(db_client, owner)
    a_call_with_usage(migrated_url, account, billed=60, ago=timedelta(hours=2))  # before
    body = {"kind": "stt", "vendor": "sarvam", "unit": "audio_seconds", "inr_per_unit": "0.5"}
    db_client.put("/admin/provider-rates", json=body, headers=admin)
    put = db_client.put(
        "/admin/provider-balances/sarvam",
        json={"balance_inr": "100.00", "alert_below_inr": "80"},
        headers=admin,
    )
    assert put.status_code == 200 and Decimal(put.json()["estimated_inr"]) == 100
    read_at = "UPDATE provider_balances SET recorded_at = now() - interval '1 hour'"
    sql(migrated_url, read_at)  # staff read the balance an hour ago
    a_call_with_usage(migrated_url, account, billed=60, ago=timedelta(minutes=1))  # after
    (sarvam,) = db_client.get("/admin/provider-balances", headers=admin).json()
    assert Decimal(sarvam["spent_since_inr"]) == 30  # 60 s at 0.50: the earlier call is not counted
    assert Decimal(sarvam["estimated_inr"]) == 70 and sarvam["low"] is True
    unknown = db_client.put(
        "/admin/provider-balances/acme", json={"balance_inr": "1"}, headers=admin
    )
    assert unknown.status_code == 404


def number_in_reconcile(url: str, account: Any, e164: str) -> uuid.UUID:
    number = uuid.uuid4()
    sql(
        url,
        "INSERT INTO numbers (id, account_id, provider, e164, number_type, status)"
        " VALUES (:i, :a, 'vobiz', :e, 'regular', 'reconcile')",
        {"i": number, "a": account, "e": e164},
    )

    async def work(factory: Any) -> None:
        async with factory() as session:
            await ledger.post(
                session, uuid.UUID(str(account)), LedgerKind.NUMBER, Decimal("-600"),
                ref_type="number_purchase", ref_id=number.hex, note=f"new number {e164}",
            )  # fmt: skip
            await session.commit()

    run_db(url, work)
    return number


def test_carrier_capacity_and_purchases_settled_once(
    db_client: TestClient, migrated_url: str, admin: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AXON_MAX_CONCURRENT_CALLS", "40")
    owner = signup(db_client, email="owner@example.com")
    account = account_id(db_client, owner)
    db_client.post(
        f"/admin/accounts/{account}/credits", json={"amount": "2000", "note": "test"}, headers=admin
    )
    sql(
        migrated_url,
        "INSERT INTO numbers (account_id, provider, e164, number_type, status, channels)"
        " VALUES (:a, 'vobiz', '+911400000009', 'regular', 'active', 3)",
        {"a": account},
    )
    add_call(migrated_url, account, status="in_progress")
    kept = number_in_reconcile(migrated_url, account, "+911400000010")
    refunded = number_in_reconcile(migrated_url, account, "+911400000011")
    balance = "SELECT credit_balance FROM accounts WHERE id = :a"
    before = Decimal(str(sql(migrated_url, balance, {"a": account})))

    seen = db_client.get("/admin/capacity", headers=admin).json()
    assert (seen["max_concurrent_calls"], seen["calls_in_flight"]) == (40, 1)
    assert (seen["numbers"], seen["channels"]) == (1, 3)
    assert [n["e164"] for n in seen["reconcile"]] == ["+911400000010", "+911400000011"]

    keep = {"outcome": "kept", "provider_ref": "VB-1", "note": "carrier confirmed"}
    assert db_client.post(f"/admin/numbers/{kept}/settle", json=keep, headers=admin).json() == {
        "id": str(kept),
        "status": "active",
    }
    back = {"outcome": "refunded", "note": "carrier says not sold"}
    settled = db_client.post(f"/admin/numbers/{refunded}/settle", json=back, headers=admin)
    assert settled.json()["status"] == "released"
    after = Decimal(str(sql(migrated_url, balance, {"a": account})))
    assert after == before + 600  # only the number that was not sold is refunded
    twice = db_client.post(f"/admin/numbers/{refunded}/settle", json=back, headers=admin)
    assert twice.status_code == 409
    assert Decimal(str(sql(migrated_url, balance, {"a": account}))) == after
    assert db_client.get("/admin/capacity", headers=admin).json()["reconcile"] == []
    renews = sql(migrated_url, "SELECT renews_on FROM numbers WHERE id = :n", {"n": kept})
    assert renews is not None
    told = "SELECT count(*) FROM notifications WHERE kind = 'number_purchase'"
    assert sql(migrated_url, told) == 2
