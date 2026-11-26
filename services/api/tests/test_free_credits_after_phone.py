"""Free credits arrive with the owner's verified phone, not at sign-up (SEC test 26 Nov, M1)."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.billing.config import free_signup_credits

from .conftest import sql
from .helpers import live_employee, signup
from .test_dial_policy_integration import PHONE, api, verify_owner_phone  # noqa: F401 - fixture
from .vobiz_fake import VobizAccount

BONUSES = "SELECT count(*) FROM wallet_ledger WHERE kind = 'bonus'"


def test_sign_up_alone_gives_no_credits(api: TestClient, migrated_url: str) -> None:  # noqa: F811
    signup(api, free_credits=False)
    assert sql(migrated_url, "SELECT credit_balance FROM accounts") == 0
    assert sql(migrated_url, BONUSES) == 0


def test_the_first_verified_phone_brings_the_free_credits_once(
    api: TestClient,  # noqa: F811
    migrated_url: str,
    vobiz: VobizAccount,
) -> None:
    owner = signup(api, free_credits=False)
    live_employee(api, migrated_url, owner)
    verify_owner_phone(api, migrated_url, owner, vobiz)
    assert free_signup_credits() > 0
    assert Decimal(sql(migrated_url, "SELECT credit_balance FROM accounts")) == (
        free_signup_credits()
    )
    verify_owner_phone(api, migrated_url, owner, vobiz)  # proving it again, or a new phone
    assert sql(migrated_url, BONUSES) == 1


def test_an_account_that_had_them_at_sign_up_gets_nothing_more(
    api: TestClient,  # noqa: F811
    migrated_url: str,
    vobiz: VobizAccount,
) -> None:
    owner = signup(api)  # the helper posts what sign-up used to: the free credits
    live_employee(api, migrated_url, owner)
    verify_owner_phone(api, migrated_url, owner, vobiz)
    assert sql(migrated_url, BONUSES) == 1
    assert sql(migrated_url, "SELECT credit_balance FROM accounts") == 50


SHARED = "+918000000099"


def test_a_new_owner_proves_their_phone_from_the_shared_number_before_buying_one(
    api: TestClient,  # noqa: F811
    migrated_url: str,
    vobiz: VobizAccount,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AXON_VERIFY_FROM_NUMBER", SHARED)
    owner = signup(api, free_credits=False)  # no number bought
    verify_owner_phone(api, migrated_url, owner, vobiz)
    assert vobiz.calls[-1]["from"] == SHARED.lstrip("+")
    assert Decimal(sql(migrated_url, "SELECT credit_balance FROM accounts")) == (
        free_signup_credits()
    )


def test_one_phone_brings_the_free_credits_to_one_account_only(
    api: TestClient,  # noqa: F811
    migrated_url: str,
    vobiz: VobizAccount,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AXON_VERIFY_FROM_NUMBER", SHARED)
    verify_owner_phone(api, migrated_url, signup(api, free_credits=False), vobiz)
    other = signup(api, "other@example.com", "Other", free_credits=False)
    verify_owner_phone(api, migrated_url, other, vobiz)  # the same phone
    assert sql(migrated_url, BONUSES) == 1
    assert sql(migrated_url, "SELECT count(*) FROM accounts WHERE owner_phone IS NOT NULL") == 2


def test_codes_to_one_phone_are_capped_across_accounts(
    api: TestClient,  # noqa: F811
    vobiz: VobizAccount,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AXON_VERIFY_FROM_NUMBER", SHARED)
    first = signup(api, free_credits=False)
    second = signup(api, "other@example.com", "Other", free_credits=False)
    for owner in (first, first, second):
        sent = api.post("/accounts/owner-phone", json={"phone": PHONE}, headers=owner)
        assert sent.status_code == 202, sent.text
    capped = api.post("/accounts/owner-phone", json={"phone": PHONE}, headers=second)
    assert capped.status_code == 429
    assert len(vobiz.calls) == 3
