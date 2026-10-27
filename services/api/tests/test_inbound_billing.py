"""A call handed to a person is charged for the AI's talk time only, up to the hand-over."""

from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient

from app.providers.telephony.vobiz import VobizTelephony

from .conftest import sql
from .helpers import account_id, signup
from .test_call_billing import (  # noqa: F401 - fixtures
    ENDED,
    Cdr,
    api,
    balance,
    bill,
    cdr,
    finished_call,
)


def handed_over(url: str, call: Any, after_s: int) -> None:
    """The AI handed the call to a person `after_s` seconds after it was answered."""
    sql(url, "UPDATE calls SET answered_at = :a WHERE id = :i", {"a": ENDED, "i": call})
    sql(
        url,
        "INSERT INTO call_events (call_id, type, data, at) VALUES (:i, 'transferred', '{}', :at)",
        {"i": call, "at": ENDED + timedelta(seconds=after_s)},
    )


def charged(url: str, call: Any) -> tuple[int, str]:
    seconds = sql(url, "SELECT billed_seconds FROM calls WHERE id = :i", {"i": call})
    status = sql(url, "SELECT billing_status FROM calls WHERE id = :i", {"i": call})
    return int(seconds), str(status)


def test_the_talk_after_the_hand_over_is_not_the_employees_to_charge(
    api: TestClient,  # noqa: F811
    migrated_url: str,
    cdr: tuple[Cdr, VobizTelephony],  # noqa: F811
) -> None:
    fake, telephony = cdr
    owner = signup(api)
    call, carrier_id = finished_call(migrated_url, api, owner)
    fake.records[carrier_id] = {"billsec": 600, "duration": 610, "hangup_cause": "NORMAL_CLEARING"}
    handed_over(migrated_url, call, after_s=60)
    assert bill(migrated_url, telephony)["billed"] == 1
    assert charged(migrated_url, call) == (60, "billed")
    # Value tier is 3.5 credits a minute: one minute, not ten. The account began with 50.
    assert balance(migrated_url, account_id(api, owner)) == 46.5


def test_a_call_the_carrier_cut_short_of_the_hand_over_is_charged_what_it_ran(
    api: TestClient,  # noqa: F811
    migrated_url: str,
    cdr: tuple[Cdr, VobizTelephony],  # noqa: F811
) -> None:
    fake, telephony = cdr
    owner = signup(api)
    call, carrier_id = finished_call(migrated_url, api, owner)
    fake.records[carrier_id] = {"billsec": 20, "duration": 25, "hangup_cause": "NORMAL_CLEARING"}
    handed_over(migrated_url, call, after_s=60)  # the record says less talk than that
    bill(migrated_url, telephony)
    assert charged(migrated_url, call) == (20, "billed")


def test_a_call_never_handed_over_is_charged_all_of_it(
    api: TestClient,  # noqa: F811
    migrated_url: str,
    cdr: tuple[Cdr, VobizTelephony],  # noqa: F811
) -> None:
    fake, telephony = cdr
    owner = signup(api)
    call, carrier_id = finished_call(migrated_url, api, owner)
    fake.records[carrier_id] = {"billsec": 600, "duration": 610, "hangup_cause": "NORMAL_CLEARING"}
    sql(migrated_url, "UPDATE calls SET answered_at = :a WHERE id = :i", {"a": ENDED, "i": call})
    bill(migrated_url, telephony)
    assert charged(migrated_url, call) == (600, "billed")
