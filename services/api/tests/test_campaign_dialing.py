"""The campaign scheduler walked through simulated time against a real database and a recording
carrier: hours, holidays, concurrency, channels, retries, and every check made before a dial."""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.providers.telephony.vobiz import VobizTelephony

from .campaigning import (
    NOW,
    Carrier,
    contact_rows,
    contacts_by_status,
    end_call,
    make_campaign,
    open_calls,
    setup_bulk,
    states,
    tick,
)
from .conftest import sql

A, B, C, D = "+919876543210", "+919876543211", "+919876543212", "+919876543213"
LOCAL = ["9876543210", "9876543211", "9876543212", "9876543213"]


def test_it_places_calls_up_to_the_campaigns_concurrency(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    make_campaign(api, owner, employee, LOCAL, concurrency=2)
    placed = tick(migrated_url, adapter, NOW)
    assert [p.outcome for p in placed] == ["dialed", "dialed"] and len(fake.placed) == 2
    assert states(migrated_url) == {A: "calling", B: "calling", C: "pending", D: "pending"}
    assert tick(migrated_url, adapter, NOW + timedelta(seconds=3)) == []  # both lines are busy
    first = open_calls(migrated_url)[0]
    end_call(migrated_url, fake, adapter, first, NOW + timedelta(seconds=40), answered=True)
    third = tick(migrated_url, adapter, NOW + timedelta(seconds=45))
    assert [p.outcome for p in third] == ["dialed"] and len(fake.placed) == 3
    assert states(migrated_url)[A] == "done" and states(migrated_url)[C] == "calling"


def test_the_call_is_a_bulk_call_of_the_campaign_with_its_lead_and_number(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, ["9876543210"])
    api.post(
        f"/campaigns/{campaign}/contacts",
        json=[{"phone": "9876543299", "name": "Ravi"}],
        headers=owner,
    )
    tick(migrated_url, adapter, NOW)
    row = sql(
        migrated_url,
        "SELECT channel::text || direction::text || status::text || attempt::text || is_test::text"
        " FROM calls ORDER BY created_at LIMIT 1",
    )
    assert row == "bulkoutboundringing1false"
    assert sql(migrated_url, "SELECT count(*) FROM calls WHERE campaign_id IS NOT NULL") == 2
    assert sql(migrated_url, "SELECT count(*) FROM calls WHERE contact_id IS NOT NULL") == 2
    assert sql(migrated_url, "SELECT name FROM leads WHERE phone = '+919876543299'") == "Ravi"
    body = fake.placed[0]
    assert body["from"] == "911400000001"
    assert body["answer_url"].startswith(
        f"https://engine.example.in/vobiz/answer?employee={employee}&call="
    )


def test_nothing_is_dialed_outside_the_calling_hours_and_it_says_why(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, LOCAL)
    night = datetime(2026, 11, 2, 16, 30, tzinfo=UTC)  # 22:00 IST
    assert tick(migrated_url, adapter, night) == [] and fake.placed == []
    note = api.get(f"/campaigns/{campaign}", headers=owner).json()["note"]
    assert note == "outside calling hours; calls resume 03 Nov, 09:00 IST"
    early = datetime(2026, 11, 3, 3, 29, tzinfo=UTC)  # 08:59 IST
    assert tick(migrated_url, adapter, early) == []
    opening = datetime(2026, 11, 3, 3, 30, tzinfo=UTC)  # 09:00 IST
    assert len(tick(migrated_url, adapter, opening)) == 2
    assert api.get(f"/campaigns/{campaign}", headers=owner).json()["note"] is None


def test_holidays_and_closed_weekdays_are_not_dialed(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    make_campaign(
        api,
        owner,
        employee,
        LOCAL,
        holidays=["2026-11-02"],  # NOW is Monday 2 November
        days=[0, 1, 2, 3, 4],
    )
    assert tick(migrated_url, adapter, NOW) == []  # a holiday
    saturday = NOW + timedelta(days=5)
    assert tick(migrated_url, adapter, saturday) == [] and fake.placed == []  # a closed weekday
    tuesday = NOW + timedelta(days=1)
    assert len(tick(migrated_url, adapter, tuesday)) == 2


def test_an_unanswered_contact_is_retried_after_the_gap_until_the_attempts_run_out(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    make_campaign(api, owner, employee, ["9876543210"], retries=2, retry_gap_min=30)
    now = NOW
    for attempt in (1, 2, 3):
        assert [p.outcome for p in tick(migrated_url, adapter, now)] == ["dialed"]
        end_call(
            migrated_url, fake, adapter, open_calls(migrated_url)[0], now + timedelta(seconds=20)
        )
        row = contact_rows(migrated_url)[0]
        assert row[2] == attempt
        if attempt < 3:
            assert row[1] == "pending" and row[3] == now + timedelta(seconds=20, minutes=30)
            assert tick(migrated_url, adapter, now + timedelta(minutes=29)) == []  # not yet
            now = row[3]
    status, attempts, _, reason = contact_rows(migrated_url)[0][1:]
    assert (status, attempts, reason) == ("exhausted", 3, "no answer after 3 attempt(s)")
    assert len(fake.placed) == 3
    assert tick(migrated_url, adapter, now + timedelta(days=1)) == []  # never a fourth


def test_a_retry_that_would_land_after_nine_in_the_evening_waits_for_the_morning(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    make_campaign(api, owner, employee, ["9876543210"], retries=1, retry_gap_min=60)
    late = datetime(2026, 11, 2, 15, 0, tzinfo=UTC)  # 20:30 IST
    tick(migrated_url, adapter, late)
    end_call(migrated_url, fake, adapter, open_calls(migrated_url)[0], late + timedelta(minutes=1))
    assert contact_rows(migrated_url)[0][3] == datetime(2026, 11, 3, 3, 30, tzinfo=UTC)


def test_the_next_day_retry_mode_waits_for_a_later_day(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    make_campaign(api, owner, employee, ["9876543210"], retries=1, retry_mode="next_day")
    tick(migrated_url, adapter, NOW)
    end_call(migrated_url, fake, adapter, open_calls(migrated_url)[0], NOW + timedelta(seconds=30))
    assert contact_rows(migrated_url)[0][3] == datetime(2026, 11, 3, 3, 30, tzinfo=UTC)
    assert tick(migrated_url, adapter, NOW + timedelta(hours=6)) == []
    assert len(tick(migrated_url, adapter, datetime(2026, 11, 3, 3, 30, tzinfo=UTC))) == 1


def test_an_answered_call_finishes_the_contact_and_the_last_one_completes_the_campaign(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, LOCAL[:2], retries=0)
    tick(migrated_url, adapter, NOW)
    first, second = open_calls(migrated_url)
    end_call(migrated_url, fake, adapter, first, NOW + timedelta(seconds=40), answered=True)
    tick(migrated_url, adapter, NOW + timedelta(seconds=50))
    assert api.get(f"/campaigns/{campaign}", headers=owner).json()["status"] == "running"
    end_call(
        migrated_url, fake, adapter, second, NOW + timedelta(seconds=60)
    )  # no answer, no retries
    tick(migrated_url, adapter, NOW + timedelta(seconds=70))
    assert contacts_by_status(migrated_url) == {"done": 1, "exhausted": 1}
    done = api.get(f"/campaigns/{campaign}", headers=owner).json()
    assert done["status"] == "completed" and done["completed_at"] is not None
    assert tick(migrated_url, adapter, NOW + timedelta(days=1)) == []


def test_the_do_not_call_list_is_checked_again_before_every_dial(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    make_campaign(api, owner, employee, LOCAL[:2], concurrency=1)
    account = sql(migrated_url, "SELECT account_id FROM employees")
    # Added after the upload, before the call: a manual entry and a caller's own request.
    for phone, source in ((A, "manual"), (B, "caller_request")):
        sql(
            migrated_url,
            "INSERT INTO dnc_entries (account_id, phone, source) VALUES (:a, :p, :s)",
            {"a": account, "p": phone, "s": source},
        )
    assert tick(migrated_url, adapter, NOW) == [] and fake.placed == []
    rows = {phone: (status, reason) for phone, status, _, _, reason in contact_rows(migrated_url)}
    assert rows == {
        A: ("skipped", "on the do-not-call list"),
        B: ("skipped", "asked not to be called again"),
    }


def test_with_the_switch_off_only_people_who_asked_not_to_be_called_are_skipped(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    _, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    make_campaign(api, owner, employee, LOCAL[:2], skip_dnc=False)
    account = sql(migrated_url, "SELECT account_id FROM employees")
    for phone, source in ((A, "manual"), (B, "caller_request")):
        sql(
            migrated_url,
            "INSERT INTO dnc_entries (account_id, phone, source) VALUES (:a, :p, :s)",
            {"a": account, "p": phone, "s": source},
        )
    tick(migrated_url, adapter, NOW)
    assert states(migrated_url) == {A: "calling", B: "skipped"}


def test_a_number_another_campaign_called_lately_is_skipped(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    make_campaign(api, owner, employee, ["9876543210"], name="First")
    tick(migrated_url, adapter, NOW)
    end_call(
        migrated_url,
        fake,
        adapter,
        open_calls(migrated_url)[0],
        NOW + timedelta(seconds=30),
        answered=True,
    )
    second = make_campaign(api, owner, employee, LOCAL[:2], name="Second", dedupe_days=7)
    tick(migrated_url, adapter, NOW + timedelta(days=3))
    reasons = sql(
        migrated_url,
        "SELECT reason FROM campaign_contacts WHERE campaign_id = :c AND phone = :p",
        {"c": second, "p": A},
    )
    assert reasons == "another campaign called this number in the last 7 day(s)"
    assert (
        sql(
            migrated_url,
            "SELECT status::text FROM campaign_contacts WHERE campaign_id = :c AND phone = :p",
            {"c": second, "p": B},
        )
        == "calling"
    )
    # A campaign that sets the window to 0 days never looks.
    third = make_campaign(api, owner, employee, [LOCAL[0]], name="Third", dedupe_days=0)
    tick(migrated_url, adapter, NOW + timedelta(days=3, minutes=1))
    assert (
        sql(
            migrated_url,
            "SELECT status::text FROM campaign_contacts WHERE campaign_id = :c",
            {"c": third},
        )
        == "calling"
    )


def test_a_number_cannot_run_more_calls_than_it_has_channels(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url, channels=1)
    campaign = make_campaign(api, owner, employee, LOCAL, concurrency=5)
    assert len(tick(migrated_url, adapter, NOW)) == 1 and len(fake.placed) == 1
    note = api.get(f"/campaigns/{campaign}", headers=owner).json()["note"]
    assert note == "waiting for a free channel on the number"
    assert tick(migrated_url, adapter, NOW + timedelta(seconds=3)) == []
    sql(migrated_url, "UPDATE numbers SET channels = 3")  # the owner bought two more lines
    assert len(tick(migrated_url, adapter, NOW + timedelta(seconds=6))) == 2


def test_an_instant_call_in_flight_on_the_same_number_holds_a_channel(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url, channels=1)
    make_campaign(api, owner, employee, LOCAL[:1])
    account = sql(migrated_url, "SELECT account_id FROM employees")
    number = sql(migrated_url, "SELECT id FROM numbers")
    sql(
        migrated_url,
        "INSERT INTO calls (account_id, employee_id, number_id, direction, channel, status)"
        " VALUES (:a, :e, :n, 'outbound', 'instant', 'in_progress')",
        {"a": account, "e": employee, "n": number},
    )
    assert tick(migrated_url, adapter, NOW) == [] and fake.placed == []


def test_campaigns_share_a_numbers_channels_oldest_first(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    _, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url, channels=3)
    old = make_campaign(api, owner, employee, LOCAL, name="Old", concurrency=2, dedupe_days=0)
    new = make_campaign(
        api,
        owner,
        employee,
        ["9876543250", "9876543251", "9876543252"],
        name="New",
        concurrency=3,
        dedupe_days=0,
    )
    tick(migrated_url, adapter, NOW)
    counts = {
        cid: sql(migrated_url, "SELECT count(*) FROM calls WHERE campaign_id = :c", {"c": cid})
        for cid in (old, new)
    }
    assert counts == {old: 2, new: 1}  # the old one took its two lines, the new one got the last


def test_credits_are_needed_to_dial_and_the_campaign_waits_for_them(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, LOCAL[:1])
    sql(migrated_url, "UPDATE accounts SET credit_balance = 0")
    assert tick(migrated_url, adapter, NOW) == [] and fake.placed == []
    note = api.get(f"/campaigns/{campaign}", headers=owner).json()
    assert note["note"] == "no credits left: top up to keep calling" and note["status"] == "running"
    sql(migrated_url, "UPDATE accounts SET credit_balance = 100")
    assert len(tick(migrated_url, adapter, NOW + timedelta(seconds=3))) == 1


def test_a_rule_that_forbids_the_calls_pauses_the_campaign_and_tells_the_owner(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, LOCAL[:1])
    # The number is swapped for a regular one after the start: promotional calls may not use it.
    sql(migrated_url, "UPDATE numbers SET number_type = 'regular'")
    assert tick(migrated_url, adapter, NOW) == [] and fake.placed == []
    paused = api.get(f"/campaigns/{campaign}", headers=owner).json()
    assert paused["status"] == "paused" and "promotional" in paused["note"]
    notices = api.get("/notifications", headers=owner).json()["items"]
    assert "campaign_paused" in [n["kind"] for n in notices]
    assert tick(migrated_url, adapter, NOW + timedelta(seconds=3)) == []


def test_a_campaign_can_declare_its_own_purpose(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    _, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url, number_type="regular")
    made = api.post(
        "/campaigns",
        json={"employee_id": employee, "name": "Reminders", "purpose": "transactional"},
        headers=owner,
    )
    campaign = made.json()["id"]
    api.post(
        f"/campaigns/{campaign}/contacts/import",
        json={"format": "paste", "text": "9876543210"},
        headers=owner,
    )
    api.post(f"/campaigns/{campaign}/consent", json={"confirm": True}, headers=owner)
    started = api.post(f"/campaigns/{campaign}/start", headers=owner)
    assert started.status_code == 200, started.text  # transactional may use a regular number
    assert len(tick(migrated_url, adapter, NOW)) == 1


def test_an_employee_that_is_not_live_does_not_dial(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    _, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, LOCAL[:1])
    api.post(f"/employees/{employee}/deactivate", headers=owner)
    assert tick(migrated_url, adapter, NOW) == []
    note = api.get(f"/campaigns/{campaign}", headers=owner).json()["note"]
    assert note == "the employee is not live"
    api.post(f"/employees/{employee}/activate", headers=owner)
    assert len(tick(migrated_url, adapter, NOW + timedelta(seconds=3))) == 1


def test_a_refused_dial_is_a_failed_attempt_and_an_unknown_one_is_never_retried(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    make_campaign(api, owner, employee, LOCAL[:2], retries=2, concurrency=1)
    fake.fail_next = True  # the carrier says no (HTTP 402): nothing was placed
    assert [p.outcome for p in tick(migrated_url, adapter, NOW)] == ["failed"]
    first = contact_rows(migrated_url)[0]
    assert first[1] == "pending" and first[2] == 1  # a plain failed attempt: the ladder goes on
    fake.timeout_next = True  # no answer from the carrier at all: it may have placed the call
    assert [p.outcome for p in tick(migrated_url, adapter, NOW + timedelta(seconds=3))] == ["held"]
    row = contact_rows(migrated_url)[1]
    assert row[1] == "exhausted" and "nobody knows" in str(row[4])
    assert (
        sql(migrated_url, "SELECT billing_status FROM calls WHERE billing_status IS NOT NULL")
        == "reconcile"
    )
    tick(
        migrated_url, adapter, NOW + timedelta(days=2)
    )  # the first contact's retry, not the second
    assert contact_rows(migrated_url)[1][1] == "exhausted"  # never called again on a guess


def test_a_scheduled_campaign_starts_when_its_time_comes(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    _, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, LOCAL[:1], start=False)
    when = datetime.now(UTC) + timedelta(days=2)
    scheduled = api.post(
        f"/campaigns/{campaign}/start", json={"start_at": when.isoformat()}, headers=owner
    )
    assert scheduled.json()["status"] == "scheduled"
    assert tick(migrated_url, adapter, when - timedelta(minutes=1)) == []
    sql(migrated_url, "UPDATE campaigns SET scheduled_at = :t", {"t": NOW - timedelta(minutes=1)})
    assert len(tick(migrated_url, adapter, NOW)) == 1
    assert api.get(f"/campaigns/{campaign}", headers=owner).json()["status"] == "running"


def test_a_repeating_campaign_goes_back_to_the_start_for_its_next_run(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    fake, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, LOCAL[:2], repeat="daily", retries=0)
    sql(migrated_url, "UPDATE campaigns SET started_at = :t", {"t": NOW})
    tick(migrated_url, adapter, NOW)
    for call, answered in zip(open_calls(migrated_url), (True, False), strict=True):
        end_call(migrated_url, fake, adapter, call, NOW + timedelta(seconds=40), answered=answered)
    tick(migrated_url, adapter, NOW + timedelta(seconds=50))
    again = api.get(f"/campaigns/{campaign}", headers=owner).json()
    assert again["status"] == "scheduled" and again["contacts"]["pending"] == 2
    assert datetime.fromisoformat(again["scheduled_at"]) == NOW + timedelta(days=1)
    assert tick(migrated_url, adapter, NOW + timedelta(hours=5)) == []
    assert len(tick(migrated_url, adapter, NOW + timedelta(days=1))) == 2  # the next day's run
    assert api.get(f"/campaigns/{campaign}", headers=owner).json()["status"] == "running"


def test_a_call_that_is_never_reported_is_closed_and_the_contact_is_held(
    api: TestClient, migrated_url: str, carrier: tuple[Carrier, VobizTelephony]
) -> None:
    from app.instant import dialer

    from .helpers import run_db

    fake, adapter = carrier
    employee, owner = setup_bulk(api, migrated_url)
    make_campaign(api, owner, employee, LOCAL[:1], retries=3)
    tick(migrated_url, adapter, NOW)
    fake.default_cdr = None  # the carrier has no record of it

    async def reap(factory: object) -> int:
        return await dialer.reap_stale(factory, adapter, NOW + timedelta(minutes=20))  # type: ignore[arg-type]

    assert run_db(migrated_url, reap) == 1
    status, _, _, reason = contact_rows(migrated_url)[0][1:]
    assert status == "exhausted" and "nobody knows" in str(reason)
