"""The daily email of yesterday's incoming calls: India's day, once per account, only if wanted."""

import json
from datetime import UTC, date, datetime
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.billing import alerts
from app.inbound import summary
from app.providers.email.resend import ResendEmail

from .conftest import sql
from .helpers import run_db
from .inbound_support import inbound_employee

MONDAY = datetime(2026, 11, 2, 5, 30, tzinfo=UTC)  # 11:00 IST
TUESDAY_9 = datetime(2026, 11, 3, 3, 30, tzinfo=UTC)  # 09:00 IST: yesterday was Monday
TUESDAY_7 = datetime(2026, 11, 3, 2, 0, tzinfo=UTC)  # 07:30 IST: too early to send


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """An email provider that records what it is asked to send."""
    mails: list[dict[str, Any]] = []

    def resend(request: httpx.Request) -> httpx.Response:
        mails.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "email-1"})

    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("EMAIL_FROM", "summary@example.in")
    monkeypatch.setattr(
        alerts, "require", lambda _kind: ResendEmail(transport=httpx.MockTransport(resend))
    )
    return mails


def incoming(
    url: str,
    employee: str,
    when: datetime,
    *,
    miss: str | None = None,
    duration: int = 0,
    test: bool = False,
    direction: str = "inbound",
) -> str:
    account = sql(url, "SELECT account_id FROM employees WHERE id = :e", {"e": employee})
    status = "no_answer" if miss else "completed"
    call = sql(
        url,
        "INSERT INTO calls (account_id, employee_id, direction, channel, status, miss_reason,"
        " duration_s, is_test, created_at) VALUES (:a, :e, :d, 'inbound', :s, :m, :t, :x, :w)"
        " RETURNING id",
        {
            "a": account,
            "e": employee,
            "d": direction,
            "s": status,
            "m": miss,
            "t": duration,
            "x": test,
            "w": when,
        },
    )
    return str(call)


def send(url: str, now: datetime) -> int:
    count: int = run_db(url, lambda factory: summary.send_due(factory, now))
    return count


def test_the_day_is_one_of_india_time() -> None:
    start, end = summary.day_bounds(date(2026, 11, 2))
    assert start == datetime(2026, 11, 1, 18, 30, tzinfo=UTC)
    assert end == datetime(2026, 11, 2, 18, 30, tzinfo=UTC)


def test_yesterdays_calls_are_summarised_once_to_the_owner(
    api: TestClient, migrated_url: str, sent: list[dict[str, Any]]
) -> None:
    employee, _owner = inbound_employee(api, migrated_url)
    incoming(migrated_url, employee, MONDAY, duration=120)
    incoming(migrated_url, employee, MONDAY, miss="the line was busy")
    call = incoming(migrated_url, employee, MONDAY, duration=30)
    account = sql(migrated_url, "SELECT account_id FROM employees")
    sql(
        migrated_url,
        "INSERT INTO inbound_messages (account_id, employee_id, call_id, phone, name, body,"
        " created_at) VALUES (:a, :e, :c, '+919876543210', 'Ravi', 'Wants a quote.', :w)",
        {"a": account, "e": employee, "c": call, "w": MONDAY},
    )
    assert send(migrated_url, TUESDAY_9) == 1
    (mail,) = sent
    assert mail["to"] == ["owner@example.com"]
    assert mail["subject"] == "Yesterday's calls: 2 answered, 1 missed"
    body = mail["text"]
    assert "02 Nov 2026" in body and "Talk time: 2 min 30 s" in body
    assert "1 x the line was busy" in body and "Ravi: Wants a quote." in body
    assert "Waiting for you: 1 message(s)" in body
    assert send(migrated_url, TUESDAY_9) == 0 and len(sent) == 1  # once per account per day


def test_only_the_india_day_is_counted_and_only_real_incoming_calls(
    api: TestClient, migrated_url: str, sent: list[dict[str, Any]]
) -> None:
    employee, _owner = inbound_employee(api, migrated_url)
    incoming(migrated_url, employee, datetime(2026, 11, 1, 18, 45, tzinfo=UTC))  # 00:15 IST Mon
    incoming(migrated_url, employee, datetime(2026, 11, 1, 18, 15, tzinfo=UTC))  # still Sunday
    incoming(migrated_url, employee, datetime(2026, 11, 2, 18, 45, tzinfo=UTC))  # already Tuesday
    incoming(migrated_url, employee, MONDAY, test=True)
    incoming(migrated_url, employee, MONDAY, direction="outbound")
    assert send(migrated_url, TUESDAY_9) == 1
    assert "Answered: 1  -  Missed: 0" in sent[0]["text"]


def test_nothing_is_sent_before_eight_in_the_morning_and_nothing_is_lost_by_waiting(
    api: TestClient, migrated_url: str, sent: list[dict[str, Any]]
) -> None:
    employee, _owner = inbound_employee(api, migrated_url)
    incoming(migrated_url, employee, MONDAY)
    assert send(migrated_url, TUESDAY_7) == 0 and sent == []
    assert send(migrated_url, TUESDAY_9) == 1


def test_a_day_without_incoming_calls_sends_nothing(
    api: TestClient, migrated_url: str, sent: list[dict[str, Any]]
) -> None:
    employee, _owner = inbound_employee(api, migrated_url)
    incoming(migrated_url, employee, MONDAY, direction="outbound")
    assert send(migrated_url, TUESDAY_9) == 0 and sent == []


def test_an_employee_with_the_summary_switched_off_is_left_out(
    api: TestClient, migrated_url: str, sent: list[dict[str, Any]]
) -> None:
    employee, _owner = inbound_employee(api, migrated_url, settings={"daily_summary": False})
    incoming(migrated_url, employee, MONDAY)
    assert send(migrated_url, TUESDAY_9) == 0 and sent == []
    assert sql(migrated_url, "SELECT count(*) FROM daily_summaries") == 1  # the day is taken


def test_without_an_email_provider_nothing_is_claimed_so_it_goes_out_once_there_is_one(
    api: TestClient,
    migrated_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    employee, _owner = inbound_employee(api, migrated_url)
    incoming(migrated_url, employee, MONDAY)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    assert send(migrated_url, TUESDAY_9) == 0
    assert sql(migrated_url, "SELECT count(*) FROM daily_summaries") == 0
    mails: list[dict[str, Any]] = []

    def resend(request: httpx.Request) -> httpx.Response:
        mails.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "email-1"})

    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("EMAIL_FROM", "summary@example.in")
    monkeypatch.setattr(
        alerts, "require", lambda _kind: ResendEmail(transport=httpx.MockTransport(resend))
    )
    assert send(migrated_url, TUESDAY_9) == 1 and len(mails) == 1
