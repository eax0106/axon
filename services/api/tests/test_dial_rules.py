"""The purpose x number-type rule table: the defaults, strict and relaxed Instant, fail closed."""

import itertools
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.instant import policy
from app.models import Employee, NumberType, PhoneNumber, Purpose

from .conftest import sql
from .helpers import run_db, seed, signup

PURPOSES = ("promotional", "service", "transactional")
TYPES = ("regular", "140", "1600")
CONTEXTS = ("outbound", "callback", "inbound", "instant")

# The launch table, written out: outbound promotional calls need a 140-series number, a call-back
# or an answered call may use a regular number, 1600 is for service and transactional only, and
# 140 is for promotional only. `instant` is what a relaxed Instant setting reads.
ALLOWED = {
    # (purpose, number type): contexts in which it is allowed
    ("promotional", "regular"): {"callback", "inbound", "instant"},
    ("promotional", "140"): {"outbound", "callback", "inbound", "instant"},
    ("promotional", "1600"): {"inbound"},
    ("service", "regular"): {"outbound", "callback", "inbound", "instant"},
    ("service", "140"): {"inbound"},
    ("service", "1600"): {"outbound", "callback", "inbound", "instant"},
    ("transactional", "regular"): {"outbound", "callback", "inbound", "instant"},
    ("transactional", "140"): {"inbound"},
    ("transactional", "1600"): {"outbound", "callback", "inbound", "instant"},
}


@pytest.fixture
def api(db_client: TestClient, migrated_url: str) -> TestClient:
    seed(migrated_url)
    return db_client


def verdict(url: str, purpose: str, number_type: str, context: str) -> policy.Verdict:
    async def work(factory: Any) -> policy.Verdict:
        async with factory() as session:
            employee = Employee(purpose=Purpose(purpose))
            number = PhoneNumber(number_type=NumberType(number_type))
            return await policy.check_dial(session, employee, number, context)  # type: ignore[arg-type]

    result: policy.Verdict = run_db(url, work)
    return result


def admin(url: str, api: TestClient) -> dict[str, str]:
    headers = signup(api, "admin@example.com", "Platform")
    sql(url, "UPDATE users SET is_platform_admin = true WHERE email = 'admin@example.com'")
    return headers


def test_every_default_pairing_is_decided_as_the_table_says(
    api: TestClient, migrated_url: str
) -> None:
    assert sql(migrated_url, "SELECT count(*) FROM dial_rules") == 36  # 3 x 3 x 4, nothing missing
    for mode, contexts in (("strict", CONTEXTS[:3]), ("relaxed", CONTEXTS)):
        if mode == "relaxed":  # the `instant` rows only count once the Instant setting is relaxed
            sql(
                migrated_url,
                "INSERT INTO platform_settings (key, value) VALUES ('instant_policy', 'relaxed')",
            )
        for purpose, number_type, context in itertools.product(PURPOSES, TYPES, contexts):
            got = verdict(migrated_url, purpose, number_type, context)
            want = context in ALLOWED[(purpose, number_type)]
            assert got.allowed is want, (mode, purpose, number_type, context)
            assert bool(got.reason) is not want  # a block always says why; an allow says nothing


def test_the_instant_setting_is_strict_until_relaxed(api: TestClient, migrated_url: str) -> None:
    # Strict (the default): an Instant call is read as outbound.
    assert not verdict(migrated_url, "promotional", "regular", "instant").allowed
    for purpose, number_type in itertools.product(PURPOSES, TYPES):
        assert (
            verdict(migrated_url, purpose, number_type, "instant").allowed
            is verdict(migrated_url, purpose, number_type, "outbound").allowed
        )
    boss = admin(migrated_url, api)
    got = api.put("/admin/instant-policy", json={"mode": "relaxed"}, headers=boss)
    assert (
        got.status_code == 200
        and api.get("/admin/dial-rules", headers=boss).json()["instant_policy"] == "relaxed"
    )
    assert verdict(
        migrated_url, "promotional", "regular", "instant"
    ).allowed  # now the lead is a service call
    assert not verdict(
        migrated_url, "promotional", "regular", "outbound"
    ).allowed  # others unchanged
    assert not verdict(migrated_url, "service", "140", "instant").allowed
    api.put("/admin/instant-policy", json={"mode": "strict"}, headers=boss)
    assert not verdict(migrated_url, "promotional", "regular", "instant").allowed
    sql(migrated_url, "UPDATE platform_settings SET value = 'whatever'")
    assert not verdict(
        migrated_url, "promotional", "regular", "instant"
    ).allowed  # unknown = strict
    assert api.put("/admin/instant-policy", json={"mode": "lax"}, headers=boss).status_code == 422


def test_a_missing_rule_blocks_the_call_and_says_so(api: TestClient, migrated_url: str) -> None:
    sql(
        migrated_url,
        "DELETE FROM dial_rules WHERE purpose = 'service' AND number_type = 'regular'"
        " AND context = 'outbound'",
    )
    got = verdict(migrated_url, "service", "regular", "outbound")
    assert not got.allowed
    assert got.reason == (
        "no rule allows service calls from a regular number (outbound); an admin has to add one"
    )
    assert verdict(migrated_url, "service", "regular", "callback").allowed  # others untouched
    sql(migrated_url, "TRUNCATE dial_rules")
    assert not any(
        verdict(migrated_url, p, t, c).allowed
        for p, t, c in itertools.product(PURPOSES, TYPES, CONTEXTS)
    )  # an empty table allows nothing at all


def test_the_reasons_are_in_plain_words(api: TestClient, migrated_url: str) -> None:
    assert verdict(migrated_url, "promotional", "regular", "outbound").reason == (
        "promotional calls must be placed from a 140-series number"
    )
    assert verdict(migrated_url, "service", "140", "outbound").reason == (
        "140-series numbers are for promotional calls only"
    )
    assert verdict(migrated_url, "promotional", "1600", "callback").reason == (
        "1600-series numbers are for service and transactional calls only"
    )


def test_an_admin_can_change_a_rule_and_nobody_else_can(api: TestClient, migrated_url: str) -> None:
    boss = admin(migrated_url, api)
    owner = signup(api)
    rule = {
        "purpose": "promotional",
        "number_type": "regular",
        "context": "outbound",
        "allowed": True,
        "reason": None,
    }
    assert api.put("/admin/dial-rules", json=rule, headers=owner).status_code == 403
    assert api.get("/admin/dial-rules", headers=owner).status_code == 403
    assert api.put("/admin/dial-rules", json=rule).status_code == 401
    assert not verdict(migrated_url, "promotional", "regular", "outbound").allowed
    assert api.put("/admin/dial-rules", json=rule, headers=boss).status_code == 200
    assert verdict(migrated_url, "promotional", "regular", "outbound").allowed
    block = {**rule, "allowed": False, "reason": "legal asked us to stop"}
    api.put("/admin/dial-rules", json=block, headers=boss)
    assert (
        verdict(migrated_url, "promotional", "regular", "outbound").reason
        == "legal asked us to stop"
    )
    assert sql(migrated_url, "SELECT count(*) FROM dial_rules") == 36  # an edit, not a new row
    listed = api.get("/admin/dial-rules", headers=boss).json()
    assert len(listed["rules"]) == 36 and listed["instant_policy"] == "strict"
    for bad in (
        {**rule, "purpose": "spam"},
        {**rule, "number_type": "999"},
        {**rule, "context": "never"},
    ):
        assert api.put("/admin/dial-rules", json=bad, headers=boss).status_code == 422
