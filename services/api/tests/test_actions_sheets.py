from datetime import datetime

from fastapi.testclient import TestClient

from .actions_support import Google, connect_google, sheet_write, use
from .helpers import signup

SHEET = {"kind": "sheet_read", "name": "find_plan", "description": "d", "sheet_id": "sheet-1"}


def connected(actions_api: tuple[TestClient, Google]) -> tuple[TestClient, Google, dict[str, str]]:
    client, google = actions_api
    owner = signup(client)
    connect_google(client, owner)
    return client, google, owner


def test_a_lookup_returns_the_header_and_only_the_rows_that_match(
    actions_api: tuple[TestClient, Google], migrated_url: str
) -> None:
    client, google, owner = connected(actions_api)
    google.rows += [["Meena", "gold plus"], ["Dev", "Bronze"]]
    [found, none] = use(
        migrated_url, client, owner, [SHEET],
        [("find_plan", {"lookup": "GOLD"}), ("find_plan", {"lookup": "platinum"})],
    )  # fmt: skip
    assert found == {
        "ok": True, "columns": ["Name", "Plan"], "rows": [["Asha", "Gold"], ["Meena", "gold plus"]]
    }  # fmt: skip
    assert none["ok"] and none["rows"] == []


def test_a_lookup_is_capped_and_needs_something_to_look_for(
    actions_api: tuple[TestClient, Google], migrated_url: str
) -> None:
    client, google, owner = connected(actions_api)
    google.rows += [[f"Person {i}", "Gold"] for i in range(10)]
    [capped, empty] = use(
        migrated_url, client, owner, [{**SHEET, "max_rows": 3}],
        [("find_plan", {"lookup": "gold"}), ("find_plan", {"lookup": "  "})],
    )  # fmt: skip
    assert len(capped["rows"]) == 3 and empty["error"] == "say what to look for"


def test_a_cell_is_cut_to_a_sane_length(
    actions_api: tuple[TestClient, Google], migrated_url: str
) -> None:
    client, google, owner = connected(actions_api)
    google.rows.append(["Zed", "x" * 5000])
    [found] = use(migrated_url, client, owner, [SHEET], [("find_plan", {"lookup": "zed"})])
    assert len(found["rows"][0][1]) == 500


def test_a_write_adds_one_row_in_column_order_with_the_time_and_the_callers_number(
    actions_api: tuple[TestClient, Google], migrated_url: str
) -> None:
    client, google, owner = connected(actions_api)
    columns = [
        {"name": "name", "description": "Caller name"},
        {"name": "city", "description": "City", "required": False},
    ]
    [saved] = use(
        migrated_url, client, owner, [sheet_write(columns=columns, range="Leads!A:C")],
        [("save_lead", {"name": "Asha", "city": "Hyderabad"})],
        party_phone="+919876543210", now=lambda: datetime(2026, 11, 2, 9, 5),
    )  # fmt: skip
    assert saved == {"ok": True, "saved": True}
    assert google.appended == [
        {"values": [["2026-11-02 09:05", "+919876543210", "Asha", "Hyderabad"]]}
    ]
    [request] = [r for r in google.requests if str(r.url).split("?")[0].endswith(":append")]
    assert "Leads%21A%3AC:append" in str(request.url)
    assert request.url.params["valueInputOption"] == "RAW"  # "=1+1" stays text


def test_a_write_without_call_details_is_just_the_columns_and_a_formula_stays_text(
    actions_api: tuple[TestClient, Google], migrated_url: str
) -> None:
    client, google, owner = connected(actions_api)
    use(
        migrated_url, client, owner, [sheet_write(include_call_details=False)],
        [("save_lead", {"name": "=HYPERLINK(\"http://evil.example\")"})],
    )  # fmt: skip
    assert google.appended == [{"values": [['=HYPERLINK("http://evil.example")']]}]


def test_the_same_row_asked_for_twice_in_a_call_is_written_once_and_a_missing_value_is_named(
    actions_api: tuple[TestClient, Google], migrated_url: str
) -> None:
    client, google, owner = connected(actions_api)
    first, second, missing = use(
        migrated_url, client, owner, [sheet_write()],
        [("save_lead", {"name": "A"}), ("save_lead", {"name": "A"}), ("save_lead", {})],
    )  # fmt: skip
    assert first == {"ok": True, "saved": True}
    assert second == {"ok": True, "saved": True, "already": True}
    assert missing == {"ok": False, "error": "name is needed"} and len(google.appended) == 1


def test_an_account_that_is_not_connected_cannot_read_or_write(
    actions_api: tuple[TestClient, Google], migrated_url: str
) -> None:
    client, google = actions_api
    stranger = signup(client, "other@example.com", "Other")
    read, write = use(
        migrated_url, client, stranger, [SHEET, sheet_write()],
        [("find_plan", {"lookup": "a"}), ("save_lead", {"name": "A"})],
    )  # fmt: skip
    assert read["error"] == write["error"] == "Google is not connected"
    assert google.appended == []


def test_a_sheet_google_refuses_is_a_plain_failure(
    actions_api: tuple[TestClient, Google], migrated_url: str
) -> None:
    client, google, owner = connected(actions_api)
    google.sheets_status = 403
    [result] = use(migrated_url, client, owner, [SHEET], [("find_plan", {"lookup": "a"})])
    assert result == {"ok": False, "error": "that is not available right now"}
