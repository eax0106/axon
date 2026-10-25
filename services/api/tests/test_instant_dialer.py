"""The dialer walked through simulated time against a real database and a recording carrier."""

import asyncio
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.instant import dialer, intake
from app.models import Call, CallEvent, CallStatus, Employee
from app.providers.base import CallDetail, ProviderKind, ProviderNotConfiguredError
from app.providers.registry import require
from app.providers.telephony.vobiz import BASE_URL, VobizTelephony

from .conftest import sql
from .helpers import live_employee, run_db, seed, signup

NOW = datetime(2026, 11, 2, 5, 30, tzinfo=UTC)  # 11:00 IST, a Monday
FULL_DAY = {"window_start_min": 360, "window_end_min": 1320}


@pytest.fixture
def api(db_client: TestClient, migrated_url: str, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    seed(migrated_url)
    monkeypatch.setenv("AXON_ENGINE_PUBLIC_URL", "https://engine.example.in")
    monkeypatch.setenv("AXON_API_PUBLIC_URL", "https://api.example.in")
    return db_client


class Carrier:
    """Vobiz as the dialer sees it: places calls, and later reports how each one went."""

    def __init__(self) -> None:
        self.placed: list[dict[str, Any]] = []
        self.cdr: dict[str, dict[str, Any] | None] = {}
        self.fail_next = False
        self.default_cdr: dict[str, Any] | None = {
            "billsec": 0,
            "duration": 30,
            "hangup_cause": "USER_BUSY",
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            if self.fail_next:
                self.fail_next = False
                return httpx.Response(402, json={"error": "low balance"})
            self.placed.append(json.loads(request.content))
            return httpx.Response(
                200, json={"message": "Call fired", "request_uuid": f"vz-{len(self.placed)}"}
            )
        record = self.cdr.get(request.url.path.rsplit("/", 1)[-1], self.default_cdr)
        return httpx.Response(404) if record is None else httpx.Response(200, json=record)


@pytest.fixture
def carrier(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Carrier, VobizTelephony]]:
    monkeypatch.setenv("VOBIZ_AUTH_ID", "MA_TEST")
    monkeypatch.setenv("VOBIZ_AUTH_TOKEN", "token")
    fake = Carrier()
    transport = httpx.MockTransport(fake.handler)
    adapter = VobizTelephony(transport=transport)
    yield fake, adapter


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

    import uuid

    employee = uuid.UUID(employee)  # type: ignore[assignment]
    return run_db(url, work)  # type: ignore[no-any-return]


def tick(url: str, adapter: VobizTelephony, now: datetime) -> list[dialer.Dialed]:
    async def work(factory: Any) -> list[dialer.Dialed]:
        return await dialer.dial_due(factory, adapter, now)

    return run_db(url, work)  # type: ignore[no-any-return]


def calls(url: str) -> list[tuple[int, str, datetime | None]]:
    async def work(factory: Any) -> list[tuple[int, str, datetime | None]]:
        async with factory() as session:
            rows = await session.scalars(select(Call).order_by(Call.attempt, Call.created_at))
            return [(c.attempt, c.status.value, c.scheduled_for) for c in rows]

    return run_db(url, work)  # type: ignore[no-any-return]


def events(url: str) -> list[str]:
    async def work(factory: Any) -> list[str]:
        async with factory() as session:
            return list(await session.scalars(select(CallEvent.type).order_by(CallEvent.id)))

    return run_db(url, work)  # type: ignore[no-any-return]


def end_call(url: str, adapter: VobizTelephony, call_id: Any, now: datetime) -> str:
    async def work(factory: Any) -> str:
        return await dialer.settle_from_carrier(factory, adapter, call_id, now)

    return run_db(url, work)  # type: ignore[no-any-return]


def first_call_id(url: str) -> Any:
    return sql(url, "SELECT id FROM calls ORDER BY attempt DESC, created_at DESC LIMIT 1")


def setup(api: TestClient, url: str, **dialer_settings: Any) -> tuple[str, dict[str, str]]:
    owner = signup(api)
    employee = live_employee(api, url, owner)
    if dialer_settings:
        assert (
            api.put(
                f"/employees/{employee}/instant/dialer", json=dialer_settings, headers=owner
            ).status_code
            == 200
        )
    return employee, owner


def test_it_places_only_due_calls_from_the_employees_number(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, _ = setup(api, migrated_url, dial_delay_s=60)
    lead_in(migrated_url, employee, "98765 43210", name="Ravi")
    assert tick(migrated_url, adapter, NOW) == []  # not due for another minute
    assert fake.placed == []
    placed = tick(migrated_url, adapter, NOW + timedelta(seconds=60))
    assert [p.outcome for p in placed] == ["dialed"]
    body = fake.placed[0]
    assert (body["from"], body["to"]) == ("911400000001", "919876543210")
    assert body["answer_url"].startswith(
        f"https://engine.example.in/vobiz/answer?employee={employee}&call="
    )
    assert body["hangup_url"] == "https://api.example.in/vobiz/events"
    assert sql(migrated_url, "SELECT status::text || carrier_call_id FROM calls") == "ringingvz-1"
    assert tick(migrated_url, adapter, NOW + timedelta(seconds=90)) == []  # never dialed twice


def test_a_lead_outside_the_window_waits_for_the_next_one(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, _ = setup(api, migrated_url)  # default 9 AM to 9 PM, next_window
    night = datetime(2026, 11, 2, 16, 30, tzinfo=UTC)  # 22:00 IST
    lead_in(migrated_url, employee, "9876543210", now=night)
    # Intake already moved the first attempt to 09:00 IST next day; the dialer agrees.
    assert calls(migrated_url) == [(1, "queued", datetime(2026, 11, 3, 3, 30, tzinfo=UTC))]
    assert tick(migrated_url, adapter, night + timedelta(hours=1)) == []
    assert fake.placed == []
    assert [
        p.outcome for p in tick(migrated_url, adapter, datetime(2026, 11, 3, 3, 30, tzinfo=UTC))
    ] == ["dialed"]


def test_the_window_is_rechecked_at_dial_time_and_the_rule_applies(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, owner = setup(api, migrated_url, **FULL_DAY, out_of_window="plus_3h")
    lead_in(migrated_url, employee, "9876543210")
    # The owner narrows the window after the lead was queued: now it is 11:00 and shut.
    api.put(
        f"/employees/{employee}/instant/dialer",
        json={"window_start_min": 13 * 60, "window_end_min": 20 * 60, "out_of_window": "plus_3h"},
        headers=owner,
    )
    placed = tick(migrated_url, adapter, NOW)
    assert [p.outcome for p in placed] == ["rescheduled"] and fake.placed == []
    # +3h = 14:00 IST, inside the new window.
    assert calls(migrated_url) == [(1, "queued", NOW + timedelta(hours=3))]
    assert [p.outcome for p in tick(migrated_url, adapter, NOW + timedelta(hours=3))] == ["dialed"]


def test_hold_leaves_the_call_waiting_for_a_redial(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, owner = setup(api, migrated_url, **FULL_DAY, out_of_window="hold")
    lead_in(migrated_url, employee, "9876543210")
    api.put(
        f"/employees/{employee}/instant/dialer",
        json={"window_start_min": 13 * 60, "window_end_min": 20 * 60, "out_of_window": "hold"},
        headers=owner,
    )
    assert [p.outcome for p in tick(migrated_url, adapter, NOW)] == ["held"]
    assert calls(migrated_url) == [(1, "queued", None)]
    assert tick(migrated_url, adapter, NOW + timedelta(days=3)) == [] and fake.placed == []
    queue = api.get(f"/employees/{employee}/instant/queue", headers=owner).json()
    assert [i["state"] for i in queue["active"]] == ["held"]


def test_the_do_not_call_list_is_checked_again_before_every_dial(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, _ = setup(api, migrated_url)
    lead_in(migrated_url, employee, "9876543210")
    account = sql(migrated_url, "SELECT account_id FROM employees")
    sql(
        migrated_url,
        "INSERT INTO dnc_entries (account_id, phone, source)"
        " VALUES (:a, '+919876543210', 'caller_request')",
        {"a": account},
    )
    assert [p.outcome for p in tick(migrated_url, adapter, NOW)] == ["cancelled"]
    assert fake.placed == [] and calls(migrated_url) == [(1, "canceled", NOW)]
    assert "cancelled" in events(migrated_url)


def test_a_paused_employee_is_not_dialed_and_the_call_is_kept(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, owner = setup(api, migrated_url)
    lead_in(migrated_url, employee, "9876543210")
    api.post(f"/employees/{employee}/deactivate", headers=owner)
    assert [p.outcome for p in tick(migrated_url, adapter, NOW)] == [
        "rescheduled"
    ] and fake.placed == []
    api.post(f"/employees/{employee}/activate", headers=owner)
    assert [p.outcome for p in tick(migrated_url, adapter, NOW + timedelta(minutes=5))] == [
        "dialed"
    ]


def test_busy_and_no_answer_walk_the_ladder_to_the_tenth_attempt_and_stop(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, _ = setup(
        api, migrated_url, **FULL_DAY, retry_ladder_min=[5] * 9, out_of_window="next_window"
    )
    lead_in(migrated_url, employee, "9876543210")
    now = NOW
    for attempt in range(1, 11):
        assert [p.outcome for p in tick(migrated_url, adapter, now)] == ["dialed"], attempt
        fake.default_cdr = {
            "billsec": 0,
            "duration": 30,
            "hangup_cause": "USER_BUSY" if attempt % 2 else "NO_ANSWER",
        }
        assert (
            end_call(
                migrated_url, adapter, first_call_id(migrated_url), now + timedelta(seconds=40)
            )
            == "settled"
        )
        now += timedelta(minutes=6)  # the ladder waits 5 minutes after the 40 s call ended
        if attempt < 10:
            assert calls(migrated_url)[-1][:2] == (attempt + 1, "queued")
    rows = calls(migrated_url)
    assert [r[0] for r in rows] == list(range(1, 11))
    assert [r[1] for r in rows] == ["busy", "no_answer"] * 5
    assert tick(migrated_url, adapter, now + timedelta(days=1)) == []  # nothing left to try
    assert len(fake.placed) == 10 and "attempts_used_up" in events(migrated_url)


def test_an_answered_call_is_final(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, _ = setup(api, migrated_url)
    lead_in(migrated_url, employee, "9876543210")
    tick(migrated_url, adapter, NOW)
    fake.default_cdr = {"billsec": 42, "duration": 50, "hangup_cause": "NORMAL_CLEARING"}
    assert (
        end_call(migrated_url, adapter, first_call_id(migrated_url), NOW + timedelta(minutes=1))
        == "settled"
    )
    assert [(c[1]) for c in calls(migrated_url)] == ["completed"]
    assert sql(migrated_url, "SELECT duration_s FROM calls") == 50


def test_ending_twice_changes_nothing(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    _fake, adapter = carrier
    employee, _ = setup(api, migrated_url)
    lead_in(migrated_url, employee, "9876543210")
    tick(migrated_url, adapter, NOW)
    call = first_call_id(migrated_url)
    end_call(migrated_url, adapter, call, NOW)
    end_call(migrated_url, adapter, call, NOW)  # Vobiz retries callbacks
    assert len(calls(migrated_url)) == 2  # the busy call and one retry, not two retries


def test_the_carrier_record_decides_the_status() -> None:
    answered = dialer.outcome_of(CallDetail(True, 60, 55, "NORMAL_CLEARING"))
    assert answered is CallStatus.COMPLETED
    for cause, expected in (
        ("USER_BUSY", CallStatus.BUSY),
        ("NO_ANSWER", CallStatus.NO_ANSWER),
        ("ORIGINATOR_CANCEL", CallStatus.NO_ANSWER),
        ("CALL_REJECTED", CallStatus.FAILED),
        ("UNALLOCATED_NUMBER", CallStatus.FAILED),
        ("SERVICE_UNAVAILABLE", CallStatus.FAILED),
        ("whatever", CallStatus.FAILED),
    ):
        assert dialer.outcome_of(CallDetail(False, 20, 0, cause)) is expected, cause


def test_a_carrier_refusal_counts_as_a_failed_attempt_and_is_retried(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, _ = setup(api, migrated_url)
    lead_in(migrated_url, employee, "9876543210")
    fake.fail_next = True
    assert [p.outcome for p in tick(migrated_url, adapter, NOW)] == ["failed"]
    rows = calls(migrated_url)
    assert [(r[0], r[1]) for r in rows] == [(1, "failed"), (2, "queued")]
    assert rows[1][2] == NOW + timedelta(minutes=10)  # first rung of the default ladder
    assert "dial_failed" in events(migrated_url)


def test_stale_ringing_calls_are_settled_from_the_carrier_or_given_up_on(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, _ = setup(api, migrated_url)
    lead_in(migrated_url, employee, "9876543210")
    tick(migrated_url, adapter, NOW)

    async def reap(now: datetime) -> int:
        async def work(factory: Any) -> int:
            return await dialer.reap_stale(factory, adapter, now)

        result: int = await asyncio.to_thread(run_db, migrated_url, work)
        return result

    assert asyncio.run(reap(NOW + timedelta(minutes=2))) == 0  # not stale yet
    fake.cdr["vz-1"] = None  # the carrier has no record yet
    assert asyncio.run(reap(NOW + timedelta(minutes=5))) == 0
    assert calls(migrated_url)[0][1] == "ringing"
    assert asyncio.run(reap(NOW + timedelta(minutes=20))) == 1  # given up on
    assert [c[1] for c in calls(migrated_url)] == ["failed", "queued"]
    assert "no_carrier_report" in events(migrated_url)


def test_stale_ringing_with_a_carrier_record_uses_it(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, _ = setup(api, migrated_url)
    lead_in(migrated_url, employee, "9876543210")
    tick(migrated_url, adapter, NOW)
    fake.cdr["vz-1"] = {"billsec": 30, "duration": 40, "hangup_cause": "NORMAL_CLEARING"}

    def work(factory: Any) -> Any:
        return dialer.reap_stale(factory, adapter, NOW + timedelta(minutes=5))

    assert run_db(migrated_url, work) == 1
    assert [c[1] for c in calls(migrated_url)] == ["completed"]


def test_two_workers_never_place_the_same_call(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, _ = setup(api, migrated_url, dedup_recent_days=0)
    for n in range(6):
        lead_in(migrated_url, employee, f"98765432{n:02d}")

    async def work(factory: Any) -> list[list[dialer.Dialed]]:
        return list(
            await asyncio.gather(*(dialer.dial_due(factory, adapter, NOW) for _ in range(4)))
        )

    results = run_db(migrated_url, work)
    dialed = [d.call_id for batch in results for d in batch if d.outcome == "dialed"]
    assert len(dialed) == len(set(dialed)) == 6 and len(fake.placed) == 6


def test_test_calls_belong_to_the_builder_not_the_dialer(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, _ = setup(api, migrated_url)
    lead_in(migrated_url, employee, "9876543210")
    sql(migrated_url, "UPDATE calls SET is_test = true")
    assert tick(migrated_url, adapter, NOW) == [] and fake.placed == []


def test_without_public_urls_or_carrier_keys_the_dialer_answers_503(
    api: TestClient,
    migrated_url: str,
    carrier: tuple[Carrier, VobizTelephony],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, adapter = carrier
    monkeypatch.delenv("AXON_API_PUBLIC_URL")
    with pytest.raises(ProviderNotConfiguredError) as raised:
        tick(migrated_url, adapter, NOW)
    assert raised.value.missing_keys == ["AXON_API_PUBLIC_URL"]
    monkeypatch.delenv("VOBIZ_AUTH_ID")
    monkeypatch.delenv("VOBIZ_AUTH_TOKEN")
    with pytest.raises(ProviderNotConfiguredError) as missing:
        require(ProviderKind.TELEPHONY)
    assert missing.value.missing_keys == ["VOBIZ_AUTH_ID", "VOBIZ_AUTH_TOKEN"]
    assert BASE_URL  # the adapter targets the real Vobiz API
