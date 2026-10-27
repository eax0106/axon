import asyncio
import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.providers.whatsapp.aisensy import URL as AISENSY_URL
from app.providers.whatsapp.aisensy import AiSensyWhatsApp
from app.providers.whatsapp.interakt import URL as INTERAKT_URL
from app.providers.whatsapp.interakt import InteraktWhatsApp

from .actions_support import PHONE, WHATSAPP_ACTION, Vendor, use
from .conftest import sql
from .helpers import account_id, signup


def test_interakt_gets_the_documented_request(monkeypatch: pytest.MonkeyPatch) -> None:
    vendor = Vendor()
    adapter = InteraktWhatsApp(httpx.MockTransport(vendor.handler))
    monkeypatch.setenv("INTERAKT_API_KEY", "key-1")
    asyncio.run(adapter.send_template(PHONE, "price_list", "hi", ["Gold", "Pune"], "Asha"))
    [request] = vendor.requests
    assert str(request.url) == INTERAKT_URL and request.headers["authorization"] == "Basic key-1"
    assert json.loads(request.content) == {
        "countryCode": "+91",
        "phoneNumber": "9876543210",
        "type": "Template",
        "template": {"name": "price_list", "languageCode": "hi", "bodyValues": ["Gold", "Pune"]},
    }


def test_aisensy_gets_the_documented_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AISENSY_API_KEY", "key-2")
    vendor = Vendor()
    adapter = AiSensyWhatsApp(httpx.MockTransport(vendor.handler))
    asyncio.run(adapter.send_template(PHONE, "price_list", "hi", ["Gold"], ""))
    [request] = vendor.requests
    assert str(request.url) == AISENSY_URL
    assert json.loads(request.content) == {
        "apiKey": "key-2",
        "campaignName": "price_list",
        "destination": PHONE,
        "userName": "Customer",
        "source": "Axon call",
        "templateParams": ["Gold"],
    }


@pytest.mark.parametrize("status", [400, 429, 500])
def test_a_vendor_refusal_is_raised_not_swallowed(
    status: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INTERAKT_API_KEY", "k")
    vendor = Vendor()
    vendor.status = status
    adapter = InteraktWhatsApp(httpx.MockTransport(vendor.handler))
    with pytest.raises(RuntimeError, match="refused"):
        asyncio.run(adapter.send_template(PHONE, "t", "en", [], ""))
    vendor.status, vendor.body = 200, {"result": False}
    with pytest.raises(RuntimeError, match="refused"):
        asyncio.run(adapter.send_template(PHONE, "t", "en", [], ""))


def run(
    url: str, client: TestClient, owner: dict[str, str], calls: list[Any], **context: Any
) -> list[dict[str, Any]]:
    return use(url, client, owner, [WHATSAPP_ACTION], calls, **context)


def test_the_message_goes_to_the_person_on_the_call_with_the_values_in_order(
    interakt: Vendor, api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    [result] = run(
        migrated_url, api, owner, [("send_price", {"plan": "Gold", "city": "Pune"})],
        party_phone=PHONE, party_name="Asha",
    )  # fmt: skip
    assert result == {"ok": True, "sent": True}
    [body] = interakt.sent()
    assert body["phoneNumber"] == "9876543210"
    assert body["template"] == {
        "name": "price_list", "languageCode": "hi", "bodyValues": ["Gold", "Pune"]
    }  # fmt: skip


def test_the_ai_cannot_choose_another_number(
    interakt: Vendor, api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    run(
        migrated_url, api, owner,
        [("send_price", {"plan": "Gold", "phone": "+919000000000", "to": "+919000000000"})],
        party_phone=PHONE,
    )  # fmt: skip
    assert [b["phoneNumber"] for b in interakt.sent()] == ["9876543210"]


@pytest.mark.parametrize("phone", [None, "", "+442071234567", "+9198765", "9876543210"])
def test_a_call_with_no_indian_mobile_number_sends_nothing(
    phone: str | None, interakt: Vendor, api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    [result] = run(migrated_url, api, owner, [("send_price", {"plan": "Gold"})], party_phone=phone)
    assert result == {"ok": False, "error": "there is no WhatsApp number for this caller"}
    assert interakt.requests == []


def test_a_person_who_asked_not_to_be_contacted_gets_nothing(
    interakt: Vendor, api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    sql(
        migrated_url,
        "INSERT INTO dnc_entries (account_id, phone, source) VALUES (:a, :p, 'caller_request')",
        {"a": account_id(api, owner), "p": PHONE},
    )
    [result] = run(migrated_url, api, owner, [("send_price", {"plan": "Gold"})], party_phone=PHONE)
    assert result == {"ok": False, "error": "this person asked not to be contacted"}
    assert interakt.requests == []


def test_the_same_words_are_sent_once_per_call_and_a_missing_value_is_named(
    interakt: Vendor, api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    first, again, other, missing = run(
        migrated_url, api, owner,
        [("send_price", {"plan": "Gold"}), ("send_price", {"plan": "Gold"}),
         ("send_price", {"plan": "Silver"}), ("send_price", {})],
        party_phone=PHONE,
    )  # fmt: skip
    assert again == {"ok": True, "sent": True, "already": True}
    assert first["ok"] and other["ok"] and len(interakt.requests) == 2
    assert missing == {"ok": False, "error": "plan is needed"}


def test_a_vendor_that_refuses_is_a_plain_failure_for_the_ai(
    interakt: Vendor, api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    interakt.status = 400
    [result] = run(migrated_url, api, owner, [("send_price", {"plan": "Gold"})], party_phone=PHONE)
    assert result == {"ok": False, "error": "that is not available right now"}


def test_without_a_whatsapp_key_the_tool_fails_plainly(api: TestClient, migrated_url: str) -> None:
    owner = signup(api)
    [result] = run(migrated_url, api, owner, [("send_price", {"plan": "Gold"})], party_phone=PHONE)
    assert result == {"ok": False, "error": "that is not available right now"}
