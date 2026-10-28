import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.developer import delivery

from .conftest import sql
from .developer_support import bearer, make_key
from .helpers import account_id, live_employee, run_db, signup


def test_every_request_with_a_key_is_logged_with_its_route_status_and_time(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    employee = live_employee(api, migrated_url, owner)
    key = bearer(make_key(api, owner))
    api.get("/v1/account", headers=key)
    api.get(f"/v1/employees/{employee}?secret=1", headers=key)
    api.get(f"/v1/employees/{uuid.uuid4()}", headers=key)
    api.get("/v1/calls?limit=0", headers=key)
    api.get("/v1/account", headers={"Authorization": "Bearer axk_live_nope"})  # no account

    rows = api.get("/developer/requests", headers=owner).json()
    assert [(r["method"], r["path"], r["status_code"]) for r in rows] == [
        ("GET", "/v1/calls", 422),
        ("GET", "/v1/employees/{employee_id}", 404),
        ("GET", "/v1/employees/{employee_id}", 200),
        ("GET", "/v1/account", 200),
    ]
    assert all(r["duration_ms"] >= 0 and r["key_id"] for r in rows)
    assert "secret" not in str(rows)  # the query string is never kept


def test_the_log_is_the_accounts_own_and_can_be_filtered_and_paged(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    first, second = make_key(api, owner, "one"), make_key(api, owner, "two")
    for _ in range(3):
        api.get("/v1/account", headers=bearer(first))
    api.get(f"/v1/employees/{uuid.uuid4()}", headers=bearer(second))
    keys = {k["name"]: k["id"] for k in api.get("/developer/keys", headers=owner).json()}

    assert len(api.get("/developer/requests", headers=owner).json()) == 4
    mine = api.get("/developer/requests", params={"key_id": keys["two"]}, headers=owner).json()
    assert [r["status_code"] for r in mine] == [404]
    errors = api.get("/developer/requests?min_status=400", headers=owner).json()
    assert [r["status_code"] for r in errors] == [404]
    page = api.get("/developer/requests?limit=2", headers=owner).json()
    older = api.get(f"/developer/requests?limit=5&before={page[-1]['id']}", headers=owner).json()
    assert len(page) == 2 and len(older) == 2
    assert {r["id"] for r in page}.isdisjoint(r["id"] for r in older)

    other = signup(api, email="b@example.com", account="Other")
    assert api.get("/developer/requests", headers=other).json() == []


def test_old_log_rows_are_pruned_and_recent_ones_stay(api: TestClient, migrated_url: str) -> None:
    owner = signup(api)
    account = account_id(api, owner)
    now = datetime.now(UTC)
    for age in (45, 5):
        sql(
            migrated_url,
            "INSERT INTO api_request_log (account_id, method, path, status_code, duration_ms,"
            " created_at) VALUES (:a, 'GET', '/v1/account', 200, 3, :t)",
            {"a": account, "t": now - timedelta(days=age)},
        )
    removed = run_db(migrated_url, lambda factory: delivery.prune(factory, now))
    assert removed == 1
    assert sql(migrated_url, "SELECT count(*) FROM api_request_log") == 1


def test_status_reports_requests_errors_and_the_webhook_queue(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    account = account_id(api, owner)
    key = bearer(make_key(api, owner))
    api.get("/v1/account", headers=key)
    sql(
        migrated_url,
        "INSERT INTO api_request_log (account_id, method, path, status_code, duration_ms)"
        " VALUES (:a, 'GET', '/v1/calls', 500, 9)",
        {"a": account},
    )
    shown = api.get("/developer/status", headers=owner).json()
    assert shown["api"] == {"version": "v1", "status": "operational"}
    assert shown["requests_24h"] == 2 and shown["server_errors_24h"] == 1
    assert shown["webhooks_24h"] == {
        "delivered": 0, "failed": 0, "pending": 0, "next_attempt_at": None
    }  # fmt: skip
