from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from .conftest import sql
from .helpers import add_call, add_lead, add_member, live_employee, seed, signup

T0 = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
TRANSCRIPT = [
    {
        "role": "assistant",
        "text": "Hello, this is Asha.",
        "at": (T0 + timedelta(seconds=2)).isoformat(),
    },
    {
        "role": "user",
        "text": "Hi, tell me about solar.",
        "at": (T0 + timedelta(seconds=9)).isoformat(),
    },
]


@pytest.fixture
def api(db_client: TestClient, migrated_url: str) -> TestClient:
    seed(migrated_url)
    return db_client


def one_call(api: TestClient, url: str, **cols: Any) -> tuple[dict[str, str], str, Any]:
    owner = signup(api)
    employee = live_employee(api, url, owner)
    account = sql(url, "SELECT account_id FROM employees")
    lead = add_lead(url, account, "+919876543210", "Ravi")
    call = add_call(
        url, account, employee, lead, outcome="interested", sentiment="positive", duration_s=95,
        summary="Wants a quote.", captured={"budget": "5 lakh"}, transcript=TRANSCRIPT,
        created_at=T0, started_at=T0, ended_at=T0 + timedelta(seconds=95),
        analysis_status="done", **cols,
    )  # fmt: skip
    return owner, str(call), account


def test_detail_has_the_transcript_summary_captured_fields_and_flags(
    api: TestClient, migrated_url: str
) -> None:
    owner, call, _ = one_call(api, migrated_url, recording_key="recordings/x.wav")
    body = api.get(f"/calls/{call}", headers=owner).json()
    assert body["summary"] == "Wants a quote." and body["captured"] == {"budget": "5 lakh"}
    assert [t["role"] for t in body["transcript"]] == ["assistant", "user"]
    assert (body["name"], body["phone"], body["employee_name"]) == ("Ravi", "+919876543210", "Asha")
    assert (
        body["has_recording"] is True and body["analysis_status"] == "done" and body["attempt"] == 1
    )


def test_the_timeline_merges_turns_and_stored_events_in_time_order(
    api: TestClient, migrated_url: str
) -> None:
    owner, call, _ = one_call(api, migrated_url)
    for offset, kind, data in (
        (1, "started", "{}"),
        (30, "interruption", "{}"),
        (95, "ended", '{"reason": "caller_hung_up"}'),
    ):
        sql(
            migrated_url,
            "INSERT INTO call_events (call_id, type, data, at)"
            " VALUES (:c, :t, CAST(:d AS jsonb), :a)",
            {"c": call, "t": kind, "d": data, "a": T0 + timedelta(seconds=offset)},
        )
    timeline = api.get(f"/calls/{call}", headers=owner).json()["timeline"]
    assert [e["type"] for e in timeline] == [
        "started",
        "agent_said",
        "caller_said",
        "interruption",
        "ended",
    ]
    assert timeline[1]["data"] == {"text": "Hello, this is Asha."}
    assert timeline[-1]["data"] == {"reason": "caller_hung_up"}


def test_the_recording_link_is_presigned_and_503_without_storage_keys(
    api: TestClient, migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, call, _ = one_call(api, migrated_url, recording_key="recordings/x.wav")
    missing = api.get(f"/calls/{call}/recording", headers=owner)
    assert missing.status_code == 503 and missing.json()["kind"] == "storage"
    monkeypatch.setenv("S3_ENDPOINT_URL", "https://acct.r2.cloudflarestorage.com")
    monkeypatch.setenv("S3_BUCKET", "axon")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "AKID")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "secret")
    link = api.get(f"/calls/{call}/recording", headers=owner).json()
    assert link["expires_in"] == 900
    assert link["url"].startswith(
        "https://acct.r2.cloudflarestorage.com/axon/recordings/x.wav?X-Amz-Algorithm="
    )
    sql(migrated_url, "UPDATE calls SET recording_key = NULL")
    assert api.get(f"/calls/{call}/recording", headers=owner).status_code == 404


def test_notes_on_a_call_show_on_the_lead_and_can_be_removed_by_author_or_owner(
    api: TestClient, migrated_url: str
) -> None:
    owner, call, _ = one_call(api, migrated_url)
    member = add_member(api, migrated_url, owner)
    posted = api.post(
        f"/calls/{call}/notes", json={"body": "  Call him after Diwali  "}, headers=member
    )
    assert posted.status_code == 201 and posted.json()["body"] == "Call him after Diwali"
    assert [n["body"] for n in api.get(f"/calls/{call}/notes", headers=owner).json()] == [
        "Call him after Diwali"
    ]
    assert [n["body"] for n in api.get(f"/calls/{call}", headers=owner).json()["notes"]] == [
        "Call him after Diwali"
    ]
    lead = api.get(f"/calls/{call}", headers=owner).json()["lead_id"]
    assert [n["body"] for n in api.get(f"/leads/{lead}/notes", headers=owner).json()] == [
        "Call him after Diwali"
    ]
    for bad in ({"body": ""}, {"body": "x" * 2001}, {}):
        assert api.post(f"/calls/{call}/notes", json=bad, headers=owner).status_code == 422
    other_member = add_member(api, migrated_url, owner, "second@example.com")
    note = posted.json()["id"]
    assert api.delete(f"/notes/{note}", headers=other_member).status_code == 403
    assert api.delete(f"/notes/{note}", headers=member).status_code == 204
    again = api.post(f"/calls/{call}/notes", json={"body": "again"}, headers=member).json()["id"]
    assert api.delete(f"/notes/{again}", headers=owner).status_code == 204


def test_share_text_is_plain_lines_and_publishes_nothing(
    api: TestClient, migrated_url: str
) -> None:
    owner, call, _ = one_call(api, migrated_url)
    response = api.get(f"/calls/{call}/share-text", headers=owner)
    assert response.headers["content-type"].startswith("text/plain")
    lines = response.text.splitlines()
    assert lines[0] == "Call with Ravi (+919876543210)" and lines[1].startswith(
        "By Asha on 01 Oct 2026, 10:00"
    )
    assert lines[2] == "Outcome: interested | Sentiment: positive"
    assert "Wants a quote." in lines and "budget: 5 lakh" in lines


def test_reanalyze_only_for_skipped_or_failed_analyses(api: TestClient, migrated_url: str) -> None:
    owner, call, _ = one_call(api, migrated_url)
    assert api.post(f"/calls/{call}/reanalyze", headers=owner).status_code == 409  # already done
    sql(migrated_url, "UPDATE calls SET analysis_status = 'skipped'")
    assert api.post(f"/calls/{call}/reanalyze", headers=owner).json() == {
        "analysis_status": "pending"
    }
    assert sql(migrated_url, "SELECT analysis_status FROM calls") == "pending"


def test_everything_about_a_call_is_scoped_to_the_account(
    api: TestClient, migrated_url: str
) -> None:
    owner, call, _ = one_call(api, migrated_url, recording_key="recordings/x.wav")
    other = signup(api, "b@example.com", "B")
    for method, path in (
        ("GET", ""),
        ("GET", "/recording"),
        ("GET", "/share-text"),
        ("POST", "/reanalyze"),
        ("GET", "/notes"),
    ):
        assert api.request(method, f"/calls/{call}{path}", headers=other).status_code == 404, path
    assert api.post(f"/calls/{call}/notes", json={"body": "hi"}, headers=other).status_code == 404
    note = api.post(f"/calls/{call}/notes", json={"body": "mine"}, headers=owner).json()["id"]
    assert api.delete(f"/notes/{note}", headers=other).status_code == 404
