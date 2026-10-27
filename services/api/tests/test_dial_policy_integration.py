"""The dial rules where they bite: the dialer, free test calls, and the owner's phone proof."""

import re
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.providers.telephony.vobiz import VobizTelephony

from .conftest import sql
from .dialing import NOW, lead_in, tick
from .helpers import account_id, live_employee, seed, signup
from .vobiz_fake import VobizAccount

PHONE = "+919876543210"


@pytest.fixture
def api(db_client: TestClient, migrated_url: str, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    seed(migrated_url)
    monkeypatch.setenv("AXON_ENGINE_PUBLIC_URL", "https://engine.example.in")
    monkeypatch.setenv("AXON_API_PUBLIC_URL", "https://api.example.in")
    return db_client


def events(url: str, kind: str) -> list[str]:
    rows = sql(
        url,
        "SELECT coalesce(array_agg(data->>'reason'), '{}') FROM call_events WHERE type = :t",
        {"t": kind},
    )
    return [str(r) for r in rows]


# --- The dialer --------------------------------------------------------------------------------


def promotional_on_regular(api: TestClient, url: str) -> tuple[str, dict[str, str]]:
    owner = signup(api)
    employee = live_employee(api, url, owner)  # on a regular-type number
    sql(url, "UPDATE employees SET purpose = 'promotional'")
    return employee, owner


def test_the_dialer_cancels_a_blocked_pairing_and_says_why(
    api: TestClient, migrated_url: str, vobiz: VobizAccount
) -> None:
    employee, _ = promotional_on_regular(api, migrated_url)
    lead_in(migrated_url, employee, "9876543210", name="Ravi")
    placed = tick(migrated_url, VobizTelephony(), NOW + timedelta(seconds=10))
    assert [p.outcome for p in placed] == ["cancelled"]
    assert vobiz.calls == []  # nothing was dialed
    assert sql(migrated_url, "SELECT status::text FROM calls") == "canceled"
    assert events(migrated_url, "cancelled") == [
        "promotional calls must be placed from a 140-series number"
    ]


def test_the_same_employee_dials_once_the_number_is_a_140_series(
    api: TestClient, migrated_url: str, vobiz: VobizAccount
) -> None:
    employee, _ = promotional_on_regular(api, migrated_url)
    sql(migrated_url, "UPDATE numbers SET number_type = '140'")
    lead_in(migrated_url, employee, "9876543210", name="Ravi")
    placed = tick(migrated_url, VobizTelephony(), NOW + timedelta(seconds=10))
    assert [p.outcome for p in placed] == ["dialed"] and len(vobiz.calls) == 1


def test_the_instant_setting_decides_whether_a_lead_who_just_enquired_may_be_called(
    api: TestClient, migrated_url: str, vobiz: VobizAccount
) -> None:
    employee, _ = promotional_on_regular(api, migrated_url)
    sql(
        migrated_url,
        "INSERT INTO platform_settings (key, value) VALUES ('instant_policy', 'relaxed')",
    )
    lead_in(migrated_url, employee, "9876543210", name="Ravi")
    placed = tick(migrated_url, VobizTelephony(), NOW + timedelta(seconds=10))
    assert [p.outcome for p in placed] == ["dialed"]  # relaxed: the regular number is fine


def test_a_service_employee_on_a_regular_number_still_dials_by_default(
    api: TestClient, migrated_url: str, vobiz: VobizAccount
) -> None:
    owner = signup(api)
    employee = live_employee(api, migrated_url, owner)
    lead_in(migrated_url, employee, "9876543210", name="Ravi")
    assert [
        p.outcome for p in tick(migrated_url, VobizTelephony(), NOW + timedelta(seconds=10))
    ] == ["dialed"]


# --- Free test calls ---------------------------------------------------------------------------


def verify_owner_phone(
    api: TestClient, url: str, owner: dict[str, str], vobiz: VobizAccount
) -> None:
    sent = api.post("/accounts/owner-phone", json={"phone": PHONE}, headers=owner)
    assert sent.status_code == 202, sent.text
    token = vobiz.calls[-1]["answer_url"].rsplit("/", 1)[-1]
    spoken = api.get(f"/public/otp/{token}").text
    code = "".join(re.findall(r"\d", spoken.split("code is")[1].split(".")[0]))
    done = api.post("/accounts/owner-phone/verify", json={"code": code}, headers=owner)
    assert done.status_code == 200, done.text


def test_a_free_test_call_needs_the_owners_phone_proved_by_a_code(
    api: TestClient, migrated_url: str, vobiz: VobizAccount
) -> None:
    owner = signup(api)
    employee = live_employee(api, migrated_url, owner)
    path = f"/employees/{employee}/test-call"
    before = api.post(path, json={"phone": PHONE}, headers=owner)
    assert before.status_code == 409 and "verify your phone" in before.json()["detail"]
    verify_owner_phone(api, migrated_url, owner, vobiz)
    assert sql(migrated_url, "SELECT owner_phone FROM accounts") == PHONE
    assert (
        api.post(path, json={"phone": "+919000000001"}, headers=owner).status_code == 403
    )  # not theirs
    own = api.post(path, headers=owner)  # no number given: the verified one
    assert own.status_code == 202
    assert vobiz.calls[-1]["to"] == PHONE.lstrip("+") and vobiz.calls[-1]["from"] == "911400000001"
    assert sql(migrated_url, "SELECT is_test FROM calls ORDER BY created_at DESC LIMIT 1") is True


def test_test_calls_go_through_do_not_call_and_the_rule_table(
    api: TestClient, migrated_url: str, vobiz: VobizAccount
) -> None:
    owner = signup(api)
    employee = live_employee(api, migrated_url, owner)
    verify_owner_phone(api, migrated_url, owner, vobiz)
    path = f"/employees/{employee}/test-call"
    sql(
        migrated_url,
        "INSERT INTO dnc_entries (account_id, phone, source) VALUES (:a, :p, 'manual')",
        {"a": account_id(api, owner), "p": PHONE},
    )
    dnc = api.post(path, headers=owner)
    assert dnc.status_code == 409 and "do-not-call" in dnc.json()["detail"]
    sql(migrated_url, "DELETE FROM dnc_entries")
    sql(migrated_url, "UPDATE employees SET purpose = 'promotional'")  # on a regular number
    blocked = api.post(path, headers=owner)
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "promotional calls must be placed from a 140-series number"
    assert sql(migrated_url, "SELECT count(*) FROM calls WHERE is_test") == 0  # nothing was placed
    calls_before = len(vobiz.calls)
    sql(migrated_url, "UPDATE numbers SET number_type = '140'")
    assert api.post(path, headers=owner).status_code == 202 and len(vobiz.calls) == calls_before + 1


# --- The one-time code -------------------------------------------------------------------------


def code_of(api: TestClient, vobiz: VobizAccount) -> tuple[str, str]:
    token = vobiz.calls[-1]["answer_url"].rsplit("/", 1)[-1]
    spoken = api.get(f"/public/otp/{token}").text
    return token, "".join(re.findall(r"\d", spoken.split("code is")[1].split(".")[0]))


def test_the_code_is_spoken_to_the_phone_and_never_stored_or_put_in_a_url(
    api: TestClient, migrated_url: str, vobiz: VobizAccount
) -> None:
    owner = signup(api)
    live_employee(api, migrated_url, owner)
    assert (
        api.post("/accounts/owner-phone", json={"phone": PHONE}, headers=owner).status_code == 202
    )
    call = vobiz.calls[0]
    assert (call["to"], call["from"]) == (PHONE.lstrip("+"), "911400000001")
    token, code = code_of(api, vobiz)
    assert len(code) == 6 and code.isdigit()
    assert (
        call["answer_url"] == f"https://api.example.in/public/otp/{token}"
        and code not in call["answer_url"]
    )
    stored: Any = sql(migrated_url, "SELECT code_hash || token FROM phone_otps")
    assert code not in str(stored)  # only a hash is kept
    spoken = api.get(f"/public/otp/{token}")
    assert spoken.headers["content-type"].startswith("application/xml") and "<Speak" in spoken.text
    assert api.get("/public/otp/not-a-token").status_code == 404


def test_a_wrong_code_expired_code_or_too_many_tries_do_not_verify(
    api: TestClient, migrated_url: str, vobiz: VobizAccount
) -> None:
    owner = signup(api)
    live_employee(api, migrated_url, owner)
    api.post("/accounts/owner-phone", json={"phone": PHONE}, headers=owner)
    _, code = code_of(api, vobiz)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        assert (
            api.post(
                "/accounts/owner-phone/verify", json={"code": wrong}, headers=owner
            ).status_code
            == 400
        )
    locked = api.post("/accounts/owner-phone/verify", json={"code": code}, headers=owner)
    assert locked.status_code == 400  # five misses used the code up, even the right one now
    assert sql(migrated_url, "SELECT owner_phone FROM accounts") is None
    api.post("/accounts/owner-phone", json={"phone": PHONE}, headers=owner)  # a fresh code
    _, fresh = code_of(api, vobiz)
    sql(migrated_url, "UPDATE phone_otps SET expires_at = now() - interval '1 minute'")
    expired = api.post("/accounts/owner-phone/verify", json={"code": fresh}, headers=owner)
    assert (
        expired.status_code == 400 and sql(migrated_url, "SELECT owner_phone FROM accounts") is None
    )
    for body in ({"code": "12345"}, {"code": "abcdef"}, {}):
        assert api.post("/accounts/owner-phone/verify", json=body, headers=owner).status_code == 422


def test_asking_for_codes_is_limited_and_needs_a_number_and_an_indian_mobile(
    api: TestClient, migrated_url: str, vobiz: VobizAccount
) -> None:
    owner = signup(api)
    no_number = api.post("/accounts/owner-phone", json={"phone": PHONE}, headers=owner)
    assert no_number.status_code == 409 and vobiz.calls == []
    live_employee(api, migrated_url, owner)
    for phone in ("9876543210", "+14155550100", "+915876543210"):
        assert (
            api.post("/accounts/owner-phone", json={"phone": phone}, headers=owner).status_code
            == 422
        )
    for _ in range(3):
        assert (
            api.post("/accounts/owner-phone", json={"phone": PHONE}, headers=owner).status_code
            == 202
        )
    assert (
        api.post("/accounts/owner-phone", json={"phone": PHONE}, headers=owner).status_code == 429
    )
    assert len(vobiz.calls) == 3


def test_codes_are_503_without_carrier_keys(api: TestClient, migrated_url: str) -> None:
    owner = signup(api)
    live_employee(api, migrated_url, owner)
    got = api.post("/accounts/owner-phone", json={"phone": PHONE}, headers=owner)
    assert got.status_code == 503 and got.json()["missing_keys"] == [
        "VOBIZ_AUTH_ID",
        "VOBIZ_AUTH_TOKEN",
    ]
    assert sql(migrated_url, "SELECT count(*) FROM phone_otps") == 0
