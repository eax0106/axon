"""Free credits arrive with the owner's verified phone, not at sign-up (SEC test 26 Nov, M1)."""

from decimal import Decimal

from fastapi.testclient import TestClient

from app.billing.config import free_signup_credits

from .conftest import sql
from .helpers import live_employee, signup
from .test_dial_policy_integration import api, verify_owner_phone  # noqa: F401 - fixture
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
