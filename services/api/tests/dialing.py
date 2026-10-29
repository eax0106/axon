"""Shared by the dialer tests: Vobiz as the dialer sees it, and the calls that drive it."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

from app.instant import dialer, intake
from app.models import Employee
from app.providers.telephony.vobiz import VobizTelephony

from .helpers import run_db

NOW = datetime(2026, 11, 2, 5, 30, tzinfo=UTC)  # 11:00 IST, a Monday


class Carrier:
    """Vobiz as the dialer sees it. The dial request gets one id (`req-N`); the carrier's record
    of the finished call is keyed by the call's own id (`leg-N`), as in Plivo-style APIs. Set
    `same_ids` to model a carrier that uses one id for both."""

    def __init__(self) -> None:
        self.placed: list[dict[str, Any]] = []
        self.cdr: dict[str, dict[str, Any] | None] = {}
        self.fail_next = False
        self.refuse_with = 0  # answer every dial request with this status, if set
        self.timeout_next = False
        self.same_ids = False
        self.live: set[str] = set()
        self.parties: dict[str, tuple[str, str]] = {}  # live call -> (from, to) as Vobiz has it
        self.routed: dict[str, str] = {}  # number -> application it was attached to
        self.applications: list[dict[str, Any]] = []
        self.transfers: list[dict[str, Any]] = []
        self.routing_status = 0  # answer application and routing requests with this status, if set
        self.default_cdr: dict[str, Any] | None = {
            "billsec": 0,
            "duration": 30,
            "hangup_cause": "USER_BUSY",
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode()
        routing = path.endswith(("/Application/", "/application"))
        if request.method == "POST" and routing and self.routing_status:
            return httpx.Response(self.routing_status, json={"error": "carrier trouble"})
        if request.method == "POST" and path.endswith("/Application/"):
            self.applications.append(json.loads(request.content))
            return httpx.Response(201, json={"app_id": f"app_{len(self.applications)}"})
        if request.method == "POST" and path.endswith("/application"):
            number = path.split("/numbers/")[1].removesuffix("/application").replace("%2B", "+")
            self.routed[number] = json.loads(request.content)["application_id"]
            return httpx.Response(200, json={"message": "Number attached to application"})
        if request.method == "POST" and path.rstrip("/").split("/")[-2:-1] == ["Call"]:
            self.transfers.append(
                {"call": path.rstrip("/").split("/")[-1], **json.loads(request.content)}
            )
            return httpx.Response(202, json={"message": "call transferred"})
        if request.method == "POST":
            if self.timeout_next:
                self.timeout_next = False
                raise httpx.ReadTimeout("no answer from the carrier", request=request)
            if self.fail_next:
                self.fail_next = False
                return httpx.Response(402, json={"error": "low balance"})
            if self.refuse_with:
                return httpx.Response(self.refuse_with, json={"error": "carrier trouble"})
            self.placed.append(json.loads(request.content))
            return httpx.Response(
                200, json={"message": "Call fired", "request_uuid": f"req-{len(self.placed)}"}
            )
        carrier_id = request.url.path.rsplit("/", 1)[-1]
        if "/cdr/" not in request.url.path:  # a live call (is_live, live_parties)
            if carrier_id not in self.live:
                return httpx.Response(404)
            caller, called = self.parties.get(carrier_id, ("", ""))
            return httpx.Response(200, json={"call_uuid": carrier_id, "from": caller, "to": called})
        if carrier_id.startswith("req-") and not self.same_ids:
            return httpx.Response(404)
        record = self.cdr.get(carrier_id, self.default_cdr)
        return httpx.Response(404) if record is None else httpx.Response(200, json=record)


def lead_in(
    url: str, employee: str, phone: str, now: datetime = NOW, **payload: Any
) -> intake.Result:
    async def work(factory: Any) -> intake.Result:
        async with factory() as session:
            row = await session.get(Employee, employee)
            result: intake.Result = await intake.process(
                session, row, {"phone": phone, **payload}, source="website", now=now
            )
            return result

    employee = uuid.UUID(employee)  # type: ignore[assignment]
    return run_db(url, work)  # type: ignore[no-any-return]


def tick(url: str, adapter: VobizTelephony, now: datetime) -> list[dialer.Dialed]:
    async def work(factory: Any) -> list[dialer.Dialed]:
        return await dialer.dial_due(factory, adapter, now)

    return run_db(url, work)  # type: ignore[no-any-return]
