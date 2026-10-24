import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from .helpers import add_member, seed, signup


@pytest.fixture
def api(db_client: TestClient, migrated_url: str) -> TestClient:
    seed(migrated_url)
    return db_client


def hire(api: TestClient, headers: dict[str, str], **fields: Any) -> dict[str, Any]:
    body = {"channel": "instant", "language": "en", **fields}
    response = api.post("/employees", json=body, headers=headers)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created


def test_create_gets_defaults_a_value_voice_and_an_empty_script(api: TestClient) -> None:
    owner = signup(api)
    employee = hire(api, owner, name="Asha", language="te", extra_languages=["en"])
    assert employee["status"] == "draft" and employee["purpose"] == "service"
    assert employee["voice"]["tier"] == "value" and "te" in employee["voice"]["languages"]
    assert employee["script"]["faq"] == [] and employee["script"]["strictness"] == 3
    assert employee["avatar"]["initials"] == "A" and 0 <= employee["avatar"]["hue"] < 360
    assert employee["has_pending_edits"] is True and employee["published_version"] is None
    assert hire(api, owner, channel="bulk")["purpose"] == "promotional"


def test_create_rejects_bad_languages_and_voices(api: TestClient) -> None:
    owner = signup(api)
    for body in (
        {"language": "ta"},
        {"language": "en", "extra_languages": ["en"]},
        {"language": "en", "extra_languages": ["hi", "hi"]},
        {"language": "en", "voice_id": str(uuid.uuid4())},
    ):
        assert (
            api.post("/employees", json={"channel": "bulk", **body}, headers=owner).status_code
            == 422
        )
    telugu_only = next(
        v
        for v in api.get("/voices?tier=standard", headers=owner).json()
        if v["languages"] == ["te"]
    )
    response = api.post(
        "/employees",
        json={"channel": "bulk", "language": "hi", "voice_id": telugu_only["id"]},
        headers=owner,
    )
    assert response.status_code == 422 and "does not speak" in response.text


def test_everything_is_scoped_to_the_callers_account(api: TestClient) -> None:
    mine, theirs = signup(api, "a@example.com", "A"), signup(api, "b@example.com", "B")
    employee = hire(api, mine)
    path = f"/employees/{employee['id']}"
    assert api.get(path, headers=theirs).status_code == 404
    assert api.get("/employees", headers=theirs).json() == []
    calls: tuple[tuple[str, str, dict[str, Any] | None], ...] = (
        ("PATCH", "", {"name": "x"}),
        ("DELETE", "", None),
        ("POST", "/duplicate", None),
        ("PUT", "/script", {}),
        ("PUT", "/settings", {}),
        ("GET", "/prompt", None),
        ("POST", "/publish", None),
        ("POST", "/revert", None),
        ("GET", "/versions", None),
        ("POST", "/versions/1/restore", None),
        ("POST", "/activate", None),
        ("POST", "/deactivate", None),
        ("POST", "/switch-mode", {"channel": "bulk"}),
        ("POST", "/reset", None),
    )
    for method, suffix, body in calls:
        response = api.request(method, path + suffix, headers=theirs, json=body)
        assert response.status_code == 404, (method, suffix, response.status_code)
    assert api.get(path, headers=mine).status_code == 200


def test_owner_only_actions_are_refused_to_members(api: TestClient, migrated_url: str) -> None:
    owner = signup(api)
    member = add_member(api, migrated_url, owner)
    employee = hire(api, owner)
    path = f"/employees/{employee['id']}"
    assert api.patch(path, json={"name": "Renamed"}, headers=member).status_code == 200
    assert api.post(path + "/publish", headers=member).status_code == 200
    for method, suffix in (
        ("delete", ""),
        ("post", "/activate"),
        ("post", "/deactivate"),
        ("post", "/reset"),
    ):
        assert getattr(api, method)(path + suffix, headers=member).status_code == 403
    assert (
        api.post(path + "/switch-mode", json={"channel": "bulk"}, headers=member).status_code == 403
    )
    assert api.delete(path, headers=owner).status_code == 204


def test_script_edits_stay_pending_until_published(api: TestClient) -> None:
    owner = signup(api)
    employee = hire(api, owner)
    path = f"/employees/{employee['id']}"
    script = {"welcome_message": "Hello!", "sections": [{"title": "Reason", "body": "Ask why."}]}
    assert api.put(path + "/script", json=script, headers=owner).json()["has_pending_edits"] is True
    published = api.post(path + "/publish", headers=owner).json()
    assert published["has_pending_edits"] is False and published["published_version"] == 1
    assert published["status"] == "training"
    edited = api.put(
        path + "/script", json={**script, "welcome_message": "Hi!"}, headers=owner
    ).json()
    assert edited["has_pending_edits"] is True
    live = api.get(path + "/prompt?source=live", headers=owner).json()["prompt"]
    draft = api.get(path + "/prompt?source=draft", headers=owner).json()["prompt"]
    assert "Hello!" in live and "Hi!" not in live and "Hi!" in draft


def test_voice_and_capture_settings_apply_without_a_publish(api: TestClient) -> None:
    owner = signup(api)
    employee = hire(api, owner)
    path = f"/employees/{employee['id']}"
    api.post(path + "/publish", headers=owner)
    settings = {
        "tts_speed": 1.2,
        "ambience": "office",
        "capture": [{"name": "budget", "description": "Monthly budget"}],
    }
    updated = api.put(path + "/settings", json=settings, headers=owner).json()
    assert updated["settings"]["ambience"] == "office" and updated["has_pending_edits"] is False
    live = api.get(path + "/prompt?source=live", headers=owner).json()["prompt"]
    assert "- budget: Monthly budget" in live


def test_script_validation_and_the_permanent_faq(api: TestClient) -> None:
    owner = signup(api)
    path = f"/employees/{hire(api, owner)['id']}"
    bad_scripts: list[dict[str, Any]] = [
        {"strictness": 0},
        {"strictness": 6},
        {"pre_call_variables": ["Bad Name"]},
        {"pre_call_variables": ["a", "a"]},
        {"faq": [{"question": "", "answer": "x"}]},
        {
            "sections": [
                {"id": "s", "title": "a", "body": "b"},
                {"id": "s", "title": "c", "body": "d"},
            ]
        },
        {"faq": None},
    ]
    for bad in bad_scripts:
        assert api.put(path + "/script", json=bad, headers=owner).status_code == 422, bad
    # Sending a script without a faq key keeps the FAQ section: it is never removed.
    kept = api.put(path + "/script", json={"welcome_message": "x"}, headers=owner).json()
    assert kept["script"]["faq"] == []
    bad_settings: list[dict[str, Any]] = [
        {"tts_speed": 3},
        {"ambience": "beach"},
        {"capture": [{"name": "X", "description": "d"}]},
    ]
    for bad in bad_settings:
        assert api.put(path + "/settings", json=bad, headers=owner).status_code == 422


def test_sections_can_be_reordered_edited_and_deleted(api: TestClient) -> None:
    owner = signup(api)
    path = f"/employees/{hire(api, owner)['id']}"
    sections = [{"id": f"s{i}", "title": f"T{i}", "body": f"B{i}"} for i in range(3)]
    api.put(path + "/script", json={"sections": sections}, headers=owner)
    reordered = [sections[2], {**sections[0], "body": "edited"}]
    got = api.put(path + "/script", json={"sections": reordered}, headers=owner).json()["script"]
    assert [s["id"] for s in got["sections"]] == ["s2", "s0"] and got["sections"][1][
        "body"
    ] == "edited"


def test_duplicate_copies_the_draft_but_not_the_number_versions_or_status(
    api: TestClient, migrated_url: str
) -> None:
    from .conftest import sql

    owner = signup(api)
    employee = hire(api, owner, name="Asha")
    path = f"/employees/{employee['id']}"
    api.put(path + "/script", json={"welcome_message": "Hello"}, headers=owner)
    api.post(path + "/publish", headers=owner)
    copy = api.post(path + "/duplicate", headers=owner).json()
    assert copy["name"] == "Asha (copy)" and copy["status"] == "draft"
    assert copy["script"]["welcome_message"] == "Hello" and copy["published_version"] is None
    assert copy["id"] != employee["id"] and copy["number_id"] is None
    assert sql(migrated_url, "SELECT count(*) FROM employees") == 2


def test_activate_needs_a_number_then_goes_live_and_pauses(
    api: TestClient, migrated_url: str
) -> None:
    from .conftest import sql

    owner = signup(api)
    employee = hire(api, owner)
    path = f"/employees/{employee['id']}"
    assert api.post(path + "/activate", headers=owner).status_code == 409  # nothing published
    api.post(path + "/publish", headers=owner)
    response = api.post(path + "/activate", headers=owner)
    assert response.status_code == 409 and "phone number" in response.text
    account = sql(migrated_url, "SELECT account_id FROM employees")
    number = sql(
        migrated_url,
        "INSERT INTO numbers (account_id, provider, e164, number_type, status)"
        " VALUES (:a, 'vobiz', '+919000000009', 'regular', 'active') RETURNING id",
        {"a": account},
    )
    sql(migrated_url, "UPDATE employees SET number_id = :n", {"n": number})
    assert api.post(path + "/activate", headers=owner).json()["status"] == "live"
    assert api.post(path + "/deactivate", headers=owner).json()["status"] == "paused"
    assert api.post(path + "/activate", headers=owner).json()["status"] == "live"


def test_switch_mode_clears_history_pauses_and_offers_a_rewrite(
    api: TestClient, migrated_url: str
) -> None:
    from .conftest import sql

    owner = signup(api)
    employee = hire(api, owner, channel="instant")
    path = f"/employees/{employee['id']}"
    account = sql(migrated_url, "SELECT account_id FROM employees")
    sql(migrated_url, "UPDATE employees SET status = 'live'")
    sql(
        migrated_url,
        "INSERT INTO calls (account_id, employee_id, direction, channel, status)"
        " VALUES (:a, :e, 'outbound', 'instant', 'completed')",
        {"a": account, "e": employee["id"]},
    )
    assert (
        api.post(path + "/switch-mode", json={"channel": "instant"}, headers=owner).status_code
        == 409
    )
    switched = api.post(path + "/switch-mode", json={"channel": "bulk"}, headers=owner).json()
    assert switched["rewrite_offered"] is True
    assert switched["employee"]["channel"] == "bulk" and switched["employee"]["status"] == "paused"
    assert sql(migrated_url, "SELECT count(*) FROM calls") == 0


def test_reset_wipes_script_versions_settings_and_history(
    api: TestClient, migrated_url: str
) -> None:
    from .conftest import sql

    owner = signup(api)
    employee = hire(api, owner)
    path = f"/employees/{employee['id']}"
    api.put(path + "/script", json={"welcome_message": "Hello"}, headers=owner)
    api.put(path + "/settings", json={"style_pack": True}, headers=owner)
    api.post(path + "/publish", headers=owner)
    wiped = api.post(path + "/reset", headers=owner).json()
    assert wiped["status"] == "draft" and wiped["published_version"] is None
    assert wiped["script"]["welcome_message"] == "" and wiped["settings"]["style_pack"] is False
    assert sql(migrated_url, "SELECT count(*) FROM employee_versions") == 0


def test_update_changes_name_languages_and_voice_and_validates(api: TestClient) -> None:
    owner = signup(api)
    employee = hire(api, owner, language="en")
    path = f"/employees/{employee['id']}"
    changed = api.patch(
        path, json={"name": "Ravi", "language": "hi", "extra_languages": ["en"]}, headers=owner
    )
    assert changed.status_code == 200 and changed.json()["name"] == "Ravi"
    assert api.patch(path, json={"name": None}, headers=owner).status_code == 422
    assert api.patch(path, json={"voice_id": None}, headers=owner).status_code == 422
    assert api.patch(path, json={"language": "ta"}, headers=owner).status_code == 422
