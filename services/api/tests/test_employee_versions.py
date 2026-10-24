from typing import Any

import pytest
from fastapi.testclient import TestClient

from .conftest import sql
from .helpers import seed, signup


@pytest.fixture
def api(db_client: TestClient, migrated_url: str) -> TestClient:
    seed(migrated_url)
    return db_client


def make(api: TestClient) -> tuple[str, dict[str, str]]:
    owner = signup(api)
    employee = api.post(
        "/employees", json={"channel": "bulk", "language": "en"}, headers=owner
    ).json()
    return f"/employees/{employee['id']}", owner


def publish(api: TestClient, path: str, owner: dict[str, str], welcome: str) -> dict[str, Any]:
    api.put(path + "/script", json={"welcome_message": welcome}, headers=owner)
    published: dict[str, Any] = api.post(path + "/publish", headers=owner).json()
    return published


def test_exactly_the_last_three_versions_are_kept_after_five_publishes(
    api: TestClient, migrated_url: str
) -> None:
    path, owner = make(api)
    for n in range(1, 6):
        assert publish(api, path, owner, f"v{n}")["published_version"] == n
    versions = api.get(path + "/versions", headers=owner).json()
    assert [v["version"] for v in versions] == [5, 4, 3]
    assert [v["script"]["welcome_message"] for v in versions] == ["v5", "v4", "v3"]
    assert sql(migrated_url, "SELECT count(*) FROM employee_versions") == 3


def test_restore_makes_an_old_version_current_as_a_new_version(api: TestClient) -> None:
    path, owner = make(api)
    for n in range(1, 4):
        publish(api, path, owner, f"v{n}")
    restored = api.post(path + "/versions/2/restore", headers=owner).json()
    assert restored["published_version"] == 4 and restored["has_pending_edits"] is False
    assert restored["script"]["welcome_message"] == "v2"
    versions = api.get(path + "/versions", headers=owner).json()
    assert [v["version"] for v in versions] == [4, 3, 2]  # v1 aged out; still exactly three
    live = api.get(path + "/prompt?source=live", headers=owner).json()["prompt"]
    assert "v2" in live


def test_restore_of_a_version_that_aged_out_or_never_existed_is_404(api: TestClient) -> None:
    path, owner = make(api)
    for n in range(1, 6):
        publish(api, path, owner, f"v{n}")
    for version in (1, 2, 99):
        assert api.post(path + f"/versions/{version}/restore", headers=owner).status_code == 404


def test_revert_discards_pending_edits(api: TestClient) -> None:
    path, owner = make(api)
    publish(api, path, owner, "published")
    api.put(path + "/script", json={"welcome_message": "unsaved"}, headers=owner)
    reverted = api.post(path + "/revert", headers=owner).json()
    assert reverted["script"]["welcome_message"] == "published"
    assert reverted["has_pending_edits"] is False


def test_revert_before_any_publish_returns_an_empty_script(api: TestClient) -> None:
    path, owner = make(api)
    api.put(path + "/script", json={"welcome_message": "draft"}, headers=owner)
    assert api.post(path + "/revert", headers=owner).json()["script"]["welcome_message"] == ""


def test_publishing_an_unchanged_draft_still_adds_a_version(api: TestClient) -> None:
    path, owner = make(api)
    publish(api, path, owner, "same")
    assert api.post(path + "/publish", headers=owner).json()["published_version"] == 2
