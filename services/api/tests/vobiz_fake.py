"""Vobiz's number store and KYC as the adapters call them, with the requests kept for pinning."""

import json
from typing import Any

import httpx

ACCOUNT = "/api/v1/Account/MA_TEST"
INVENTORY = [
    {"e164": "+919100000001", "setup_fee": 0, "monthly_fee": 300},
    {"e164": "+919100000002", "setup_fee": 0, "monthly_fee": 300},
    {"e164": "+911400000042", "setup_fee": 100, "monthly_fee": 500},
    {"e164": "+911600000042", "setup_fee": 100, "monthly_fee": 500},
]
GOOD_PAN = "ABCDE1234F"


class VobizAccount:
    def __init__(self) -> None:
        self.inventory: list[dict[str, Any]] = [dict(row) for row in INVENTORY]
        self.requests: list[httpx.Request] = []
        self.owned: set[str] = set()
        self.fail_buy = False
        self.buy_status = 0  # answer the purchase with this HTTP status instead, if set
        self.buy_times_out = False  # the carrier sells the number but the answer never arrives
        self.fail_release = False
        self.consent_given = False  # the holder has finished DigiLocker
        self.pans_seen: list[str] = []
        self.calls: list[dict[str, Any]] = []  # outbound calls placed

    def sent(self, method: str, path_prefix: str) -> list[httpx.Request]:
        return [
            r
            for r in self.requests
            if r.method == method and r.url.raw_path.decode().startswith(ACCOUNT + path_prefix)
        ]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.raw_path.decode().split("?")[0].removeprefix(ACCOUNT)
        body: dict[str, Any] = json.loads(request.content) if request.content else {}
        if path == "/inventory/numbers":
            term = request.url.params.get("search", "")
            rows = [r for r in self.inventory if term in r["e164"] and r["e164"] not in self.owned]
            return httpx.Response(200, json={"items": rows})
        if path == "/numbers/purchase-from-inventory":
            if self.buy_status:
                return httpx.Response(self.buy_status)
            if self.fail_buy:
                return httpx.Response(402, json={"error": "insufficient carrier balance"})
            self.owned.add(body["e164"])
            if self.buy_times_out:
                raise httpx.ReadTimeout("no answer", request=request)
            return httpx.Response(200, json={"id": "num_" + body["e164"][-4:]})
        if request.method == "DELETE" and path.startswith("/numbers/"):
            if self.fail_release:
                return httpx.Response(503)
            e164 = path.removeprefix("/numbers/").replace("%2B", "+")
            if e164 not in self.owned:
                return httpx.Response(404)
            self.owned.discard(e164)
            return httpx.Response(200, json={})
        if request.method == "POST" and path == "/Call/":
            self.calls.append(body)
            return httpx.Response(200, json={"request_uuid": f"req-{len(self.calls)}"})
        if path == "/kyc/pan":
            self.pans_seen.append(body["pan"])
            ok = body["pan"] == GOOD_PAN
            return httpx.Response(
                200, json={"verified": ok, "name": body["name"].upper(), "holder_id": "h_1"}
            )
        if path == "/kyc/digilocker/initiate":
            return httpx.Response(
                200, json={"url": "https://digilocker.example/consent?s=1", "ref": "dl_1"}
            )
        if path == "/kyc/digilocker/verify":
            return httpx.Response(200, json={"verified": self.consent_given})
        if path == "/kyc/holders":
            return httpx.Response(200, json={"items": []})
        return httpx.Response(404)
