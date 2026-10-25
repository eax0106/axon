import hmac
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.instant import public

from .conftest import sql
from .helpers import add_member, live_employee, seed, signup


@pytest.fixture
def api(db_client: TestClient, migrated_url: str) -> TestClient:
    seed(migrated_url)
    return db_client


def setup_employee(
    api: TestClient, url: str, owner: dict[str, str], **kw: Any
) -> tuple[str, str, str]:
    """(employee id, intake path, secret) for a live Instant employee."""
    employee = live_employee(api, url, owner, **kw)
    overview = api.get(f"/employees/{employee}/instant", headers=owner).json()
    secret = api.post(f"/employees/{employee}/instant/secret/reveal", headers=owner).json()[
        "secret"
    ]
    return employee, overview["intake_path"], secret


def post_lead(api: TestClient, path: str, secret: str | None, body: Any) -> Any:
    headers = {"X-Axon-Lead-Secret": secret} if secret is not None else {}
    return api.post(path, json=body, headers=headers)


def test_a_lead_posted_with_the_secret_is_accepted_and_queued(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    employee, path, secret = setup_employee(api, migrated_url, owner, variables=("budget",))
    response = post_lead(
        api, path, secret, {"phone": "98765 43210", "name": "Ravi", "budget": "5 lakh"}
    )
    assert response.status_code == 202 and response.json()["status"] == "accepted"
    assert sql(migrated_url, "SELECT status::text FROM calls") == "queued"
    log = api.get(f"/employees/{employee}/instant/intake-log", headers=owner).json()
    assert [(e["source"], e["status"], e["phone"]) for e in log] == [
        ("website", "accepted", "+919876543210")
    ]


def test_duplicates_and_rejections_have_their_own_status_codes_and_log_lines(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    employee, path, secret = setup_employee(api, migrated_url, owner)
    assert post_lead(api, path, secret, {"phone": "9876543210"}).status_code == 202
    again = post_lead(api, path, secret, {"phone": "9876543210"})
    assert again.status_code == 200 and again.json()["status"] == "deduplicated"
    bad = post_lead(api, path, secret, {"phone": "12"})
    assert bad.status_code == 422 and bad.json()["status"] == "rejected"
    only_rejected = api.get(
        f"/employees/{employee}/instant/intake-log?outcome=rejected", headers=owner
    ).json()
    assert [e["status"] for e in only_rejected] == ["rejected"]
    assert len(api.get(f"/employees/{employee}/instant/intake-log", headers=owner).json()) == 3


def test_a_missing_or_wrong_secret_is_refused_and_nothing_is_written(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    _, path, secret = setup_employee(api, migrated_url, owner)
    for given in (None, "", "wrong", secret[:-1], secret + "x", secret.upper()):
        assert post_lead(api, path, given, {"phone": "9876543210"}).status_code == 401, given
    assert sql(migrated_url, "SELECT count(*) FROM lead_intake_log") == 0
    assert sql(migrated_url, "SELECT count(*) FROM calls") == 0


def test_unknown_intake_urls_and_bad_bodies(api: TestClient, migrated_url: str) -> None:
    owner = signup(api)
    _, path, secret = setup_employee(api, migrated_url, owner)
    assert (
        post_lead(api, "/lead-intake/00000000-0000-0000-0000-000000000000", secret, {}).status_code
        == 404
    )
    assert post_lead(api, path, secret, ["not", "an", "object"]).status_code == 422
    assert (
        api.post(path, content=b"not json", headers={"X-Axon-Lead-Secret": secret}).status_code
        == 422
    )


def test_the_secret_is_compared_in_constant_time(
    api: TestClient, migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[bytes, bytes]] = []
    real = hmac.compare_digest

    def spy(a: Any, b: Any) -> bool:
        seen.append((a, b))
        return real(a, b)

    monkeypatch.setattr(public, "hmac", SimpleNamespace(compare_digest=spy))
    owner = signup(api)
    _, path, secret = setup_employee(api, migrated_url, owner)
    post_lead(api, path, "guess", {"phone": "9876543210"})
    post_lead(api, path, secret, {"phone": "9876543210"})
    assert seen == [(b"guess", secret.encode()), (secret.encode(), secret.encode())]


def test_rotating_gives_a_new_secret_and_the_old_one_dies_at_once(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    employee, path, old = setup_employee(api, migrated_url, owner)
    new = api.post(f"/employees/{employee}/instant/secret/rotate", headers=owner).json()["secret"]
    assert new != old and len(new) >= 40
    assert post_lead(api, path, old, {"phone": "9876543210"}).status_code == 401
    assert post_lead(api, path, new, {"phone": "9876543210"}).status_code == 202
    assert (
        api.post(f"/employees/{employee}/instant/secret/reveal", headers=owner).json()["secret"]
        == new
    )
    assert sql(migrated_url, "SELECT rotated_at IS NOT NULL FROM lead_connections") is True


def test_the_intake_url_belongs_to_one_employee_and_is_stable(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    first, path_a, secret_a = setup_employee(api, migrated_url, owner)
    second, path_b, secret_b = setup_employee(api, migrated_url, owner, number="+911400000002")
    assert path_a != path_b and secret_a != secret_b
    again = api.get(f"/employees/{first}/instant", headers=owner).json()
    assert again["intake_path"] == path_a
    assert again["secret_header"] == "X-Axon-Lead-Secret"  # noqa: S105 - a header name
    # One employee's secret opens nothing of the other's.
    assert post_lead(api, path_b, secret_a, {"phone": "9876543210"}).status_code == 401
    assert post_lead(api, path_b, secret_b, {"phone": "9876543210"}).status_code == 202
    assert api.get(f"/employees/{first}/instant/intake-log", headers=owner).json() == []
    assert second


def test_reveal_and_rotate_are_owner_only(api: TestClient, migrated_url: str) -> None:
    owner = signup(api)
    member = add_member(api, migrated_url, owner)
    employee, _, _ = setup_employee(api, migrated_url, owner)
    for action in ("reveal", "rotate"):
        assert (
            api.post(f"/employees/{employee}/instant/secret/{action}", headers=member).status_code
            == 403
        )
    assert api.get(f"/employees/{employee}/instant", headers=member).status_code == 200
    overview = api.get(f"/employees/{employee}/instant", headers=member).json()
    assert "secret" not in overview  # the overview never carries it


def test_everything_is_scoped_to_the_account_and_to_instant_employees(
    api: TestClient, migrated_url: str
) -> None:
    owner, other = signup(api), signup(api, "b@example.com", "B")
    employee, _, _ = setup_employee(api, migrated_url, owner)
    base = f"/employees/{employee}/instant"
    calls = [
        ("GET", "", None),
        ("POST", "/secret/reveal", None),
        ("POST", "/secret/rotate", None),
        ("GET", "/dialer", None),
        ("PUT", "/dialer", {}),
        ("GET", "/intake-log", None),
        ("POST", "/test-lead", {"phone": "9876543210"}),
        ("POST", "/call", {"phone": "9876543210"}),
        ("GET", "/queue", None),
    ]
    for method, suffix, body in calls:
        assert api.request(method, base + suffix, headers=other, json=body).status_code == 404, (
            suffix
        )
    bulk = live_employee(api, migrated_url, owner, channel="bulk", number="+911400000009")
    assert api.get(f"/employees/{bulk}/instant", headers=owner).status_code == 409


def test_dialer_settings_round_trip_and_reject_what_breaks_the_hard_limits(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    employee, _, _ = setup_employee(api, migrated_url, owner)
    path = f"/employees/{employee}/instant/dialer"
    assert api.get(path, headers=owner).json()["window_start_min"] == 9 * 60  # the default
    mine = {
        "dial_delay_s": 30,
        "window_start_min": 7 * 60,
        "window_end_min": 20 * 60,
        "days": [0, 1, 2, 3, 4],
        "out_of_window": "plus_3h",
        "retry_ladder_min": [5, 15, 60],
        "dedup_recent_days": 3,
    }
    assert api.put(path, json=mine, headers=owner).json() == mine
    assert api.get(path, headers=owner).json() == mine
    assert api.get(f"/employees/{employee}/instant", headers=owner).json()["dialer"] == mine
    bad_settings: list[dict[str, Any]] = [
        {"window_start_min": 5 * 60},
        {"window_end_min": 23 * 60},
        {"retry_ladder_min": [1] * 10},
        {"out_of_window": "never"},
        {"days": []},
    ]
    for bad in bad_settings:
        assert api.put(path, json=bad, headers=owner).status_code == 422, bad
    assert api.get(path, headers=owner).json() == mine  # a rejected change changes nothing


def test_test_lead_shows_the_decision_without_a_call(api: TestClient, migrated_url: str) -> None:
    owner = signup(api)
    employee, _, _ = setup_employee(api, migrated_url, owner, variables=("budget",))
    path = f"/employees/{employee}/instant/test-lead"
    ok = api.post(
        path, json={"phone": "9876543210", "fields": {"budget": "9", "junk": "x"}}, headers=owner
    ).json()
    assert (
        ok["status"] == "accepted" and ok["variables"] == {"budget": "9"} and ok["call_id"] is None
    )
    bad = api.post(path, json={"phone": "12"}, headers=owner).json()
    assert bad["status"] == "rejected"
    assert sql(migrated_url, "SELECT count(*) FROM calls") == 0
    log = api.get(f"/employees/{employee}/instant/intake-log", headers=owner).json()
    assert {e["source"] for e in log} == {"test"} and len(log) == 2


def test_account_utc_offset_is_owner_set_and_bounded(api: TestClient, migrated_url: str) -> None:
    owner = signup(api)
    member = add_member(api, migrated_url, owner)
    assert (
        api.put(
            "/accounts/me/utc-offset", json={"utc_offset_minutes": 345}, headers=owner
        ).status_code
        == 200
    )
    assert sql(migrated_url, "SELECT utc_offset_minutes FROM accounts") == 345
    assert (
        api.put(
            "/accounts/me/utc-offset", json={"utc_offset_minutes": 345}, headers=member
        ).status_code
        == 403
    )
    bad_offsets: list[Any] = [-721, 841, "x"]
    for bad in bad_offsets:
        assert (
            api.put(
                "/accounts/me/utc-offset", json={"utc_offset_minutes": bad}, headers=owner
            ).status_code
            == 422
        )
