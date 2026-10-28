"""A failed post-call analysis is tried again with back-off, then left failed for a person."""

from datetime import timedelta

from fastapi.testclient import TestClient

from app.calls import postcall

from .test_post_call_job import NOW, Gemini, api, make_call, model_reply, process, row, setup

__all__ = ["api"]


def state(url: str, call: str) -> tuple[str, int]:
    return row(url, call, "analysis_status"), row(url, call, "analysis_attempts")


def test_a_failed_analysis_is_retried_twice_with_back_off_then_left_failed(
    api: tuple[TestClient, Gemini], migrated_url: str
) -> None:
    client, fake = api
    employee, _ = setup(client, migrated_url)
    call = make_call(migrated_url, employee)
    fake.status = 500
    assert postcall.RETRY_AFTER == (timedelta(minutes=2), timedelta(minutes=10))

    process(migrated_url, NOW)
    assert state(migrated_url, call) == ("pending", 1)
    assert process(migrated_url, NOW + timedelta(minutes=1, seconds=59)) == 0  # not before its time
    assert process(migrated_url, NOW + timedelta(minutes=2)) == 1
    assert state(migrated_url, call) == ("pending", 2)
    second = NOW + timedelta(minutes=2)
    assert process(migrated_url, second + timedelta(minutes=9)) == 0
    assert process(migrated_url, second + timedelta(minutes=10)) == 1
    assert state(migrated_url, call) == ("failed", 3)
    assert row(migrated_url, call, "analysis_error") == "HTTPStatusError"
    assert process(migrated_url, NOW + timedelta(days=1)) == 0  # left for a person
    assert len(fake.requests) == 3


def test_a_retry_that_works_finishes_the_analysis(
    api: tuple[TestClient, Gemini], migrated_url: str
) -> None:
    client, fake = api
    employee, _ = setup(client, migrated_url)
    call = make_call(migrated_url, employee)
    fake.text = "not json at all"
    process(migrated_url, NOW)
    fake.text = model_reply()
    process(migrated_url, NOW + timedelta(minutes=2))
    assert state(migrated_url, call) == ("done", 1)
    assert row(migrated_url, call, "analysis_error") is None
    assert row(migrated_url, call, "outcome") == "callback_requested"


def test_re_analysis_starts_the_count_again(
    api: tuple[TestClient, Gemini], migrated_url: str
) -> None:
    client, fake = api
    employee, owner = setup(client, migrated_url)
    call = make_call(migrated_url, employee)
    fake.status = 500
    for minutes in (0, 2, 12):
        process(migrated_url, NOW + timedelta(minutes=minutes))
    assert state(migrated_url, call) == ("failed", 3)

    again = client.post(f"/calls/{call}/reanalyze", headers=owner)
    assert again.status_code == 202
    assert state(migrated_url, call) == ("pending", 0)
    assert row(migrated_url, call, "analysis_retry_at") is None
    process(migrated_url, NOW + timedelta(minutes=13))
    assert state(migrated_url, call) == ("pending", 1)  # two retries are left again
