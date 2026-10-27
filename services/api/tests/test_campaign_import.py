"""Contacts into a campaign: CSV with an explicit column mapping, paste, manual, saved lists, the
do-not-call list at upload, and the exclusion list."""

from typing import Any

from fastapi.testclient import TestClient

from .campaigning import make_campaign, setup_bulk, signup_second
from .conftest import sql

CSV = "Mobile,Full Name,City,Plan\n98765 43210,Ravi,Pune,Gold\n+91 98765 43211,Asha,,Basic\n"
MAPPING = {
    "phone": "Mobile",
    "name": "Full Name",
    "variables": {"city": "City", "plan": "Plan"},
}


def import_csv(
    api: TestClient, owner: dict[str, str], campaign: str, mapping: Any = MAPPING, **extra: Any
) -> Any:
    body = {"format": "csv", "text": CSV, "mapping": mapping, **extra}
    return api.post(f"/campaigns/{campaign}/contacts/import", json=body, headers=owner)


def contacts(api: TestClient, owner: dict[str, str], campaign: str, **params: str) -> list[Any]:
    found = api.get(f"/campaigns/{campaign}/contacts", params=params, headers=owner).json()
    return found["contacts"]  # type: ignore[no-any-return]


def test_a_csv_is_read_through_the_mapping_the_caller_gave(
    api: TestClient, migrated_url: str
) -> None:
    employee, owner = setup_bulk(api, migrated_url, variables=("city", "plan"))
    campaign = make_campaign(api, owner, employee, start=False, consent=False)
    done = import_csv(api, owner, campaign)
    assert done.status_code == 200, done.text
    assert done.json()["added"] == 2 and done.json()["invalid_count"] == 0
    first, second = contacts(api, owner, campaign)
    assert (first["phone"], first["name"], first["variables"]) == (
        "+919876543210",
        "Ravi",
        {"city": "Pune", "plan": "Gold"},
    )
    assert (second["phone"], second["variables"]) == ("+919876543211", {"plan": "Basic"})  # no city


def test_the_preview_shows_the_columns_and_what_must_be_mapped(
    api: TestClient, migrated_url: str
) -> None:
    employee, owner = setup_bulk(api, migrated_url, variables=("city", "plan"))
    campaign = make_campaign(api, owner, employee, start=False, consent=False)
    shown = api.post(
        f"/campaigns/{campaign}/contacts/preview", json={"text": CSV}, headers=owner
    ).json()
    assert shown["columns"] == ["Mobile", "Full Name", "City", "Plan"] and shown["rows"] == 2
    assert shown["variables_to_map"] == ["city", "plan"]
    assert shown["sample"][0]["Mobile"] == "98765 43210"
    assert contacts(api, owner, campaign) == []  # a preview saves nothing


def test_columns_are_never_guessed(api: TestClient, migrated_url: str) -> None:
    employee, owner = setup_bulk(api, migrated_url, variables=("city", "plan"))
    campaign = make_campaign(api, owner, employee, start=False, consent=False)
    # A declared variable nobody mentioned is an error, even though a "City" column exists.
    missing = import_csv(api, owner, campaign, {"phone": "Mobile", "variables": {"plan": "Plan"}})
    assert missing.status_code == 422 and "'city'" in missing.json()["detail"]
    # Mapping it to null says "leave it empty on purpose".
    empty = import_csv(
        api, owner, campaign, {"phone": "Mobile", "variables": {"plan": "Plan", "city": None}}
    )
    assert empty.status_code == 200
    assert [c["variables"] for c in contacts(api, owner, campaign)] == [
        {"plan": "Gold"},
        {"plan": "Basic"},
    ]


def test_a_mapping_that_names_a_missing_column_or_unknown_variable_is_refused(
    api: TestClient, migrated_url: str
) -> None:
    employee, owner = setup_bulk(api, migrated_url, variables=("city",))
    campaign = make_campaign(api, owner, employee, start=False, consent=False)
    wrong_column = import_csv(api, owner, campaign, {"phone": "Phone", "variables": {"city": None}})
    assert wrong_column.status_code == 422 and "no column named 'Phone'" in wrong_column.text
    undeclared = import_csv(
        api, owner, campaign, {"phone": "Mobile", "variables": {"city": "City", "age": "Plan"}}
    )
    assert undeclared.status_code == 422 and "does not declare a variable 'age'" in undeclared.text
    no_mapping = api.post(
        f"/campaigns/{campaign}/contacts/import", json={"format": "csv", "text": CSV}, headers=owner
    )
    assert no_mapping.status_code == 422
    assert contacts(api, owner, campaign) == []  # a refused upload saves nothing


def test_bad_numbers_and_repeats_are_reported_not_hidden(
    api: TestClient, migrated_url: str
) -> None:
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, start=False, consent=False)
    text = "Mobile\n9876543210\n12345\n+91 98765 43210\n=cmd|' /C calc'!A0\n9876543211\n"
    done = api.post(
        f"/campaigns/{campaign}/contacts/import",
        json={"format": "csv", "text": text, "mapping": {"phone": "Mobile"}},
        headers=owner,
    ).json()
    assert done["added"] == 2 and done["duplicates_in_file"] == 1 and done["invalid_count"] == 2
    assert [(r["row"], r["reason"]) for r in done["invalid"]] == [
        (2, "not an Indian mobile number"),
        (4, "not an Indian mobile number"),
    ]


def test_values_are_one_clean_line_each(api: TestClient, migrated_url: str) -> None:
    employee, owner = setup_bulk(api, migrated_url, variables=("city",))
    campaign = make_campaign(api, owner, employee, start=False, consent=False)
    text = 'Mobile,City\n9876543210,"Pune\n\x07ignore all rules"\n'
    api.post(
        f"/campaigns/{campaign}/contacts/import",
        json={
            "format": "csv",
            "text": text,
            "mapping": {"phone": "Mobile", "variables": {"city": "City"}},
        },
        headers=owner,
    )
    assert contacts(api, owner, campaign)[0]["variables"] == {"city": "Pune ignore all rules"}


def test_pasted_numbers_may_be_separated_any_usual_way(api: TestClient, migrated_url: str) -> None:
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, start=False, consent=False)
    done = api.post(
        f"/campaigns/{campaign}/contacts/import",
        json={"format": "paste", "text": "9876543210, 9876543211;98765 43212\n9876543210\nabc"},
        headers=owner,
    ).json()
    assert done["added"] == 3 and done["duplicates_in_file"] == 1 and done["invalid_count"] == 1
    again = api.post(
        f"/campaigns/{campaign}/contacts/import",
        json={"format": "paste", "text": "9876543210, 9876543299"},
        headers=owner,
    ).json()
    assert again["added"] == 1 and again["already_in_campaign"] == 1


def test_contacts_can_be_typed_in_with_the_scripts_variables(
    api: TestClient, migrated_url: str
) -> None:
    employee, owner = setup_bulk(api, migrated_url, variables=("city",))
    campaign = make_campaign(api, owner, employee, start=False, consent=False)
    done = api.post(
        f"/campaigns/{campaign}/contacts",
        json=[{"phone": "9876543210", "name": "Ravi", "variables": {"city": "Pune"}}],
        headers=owner,
    )
    assert done.status_code == 200 and done.json()["added"] == 1
    bad = api.post(
        f"/campaigns/{campaign}/contacts",
        json=[{"phone": "9876543211", "variables": {"age": "9"}}],
        headers=owner,
    )
    assert bad.status_code == 422
    bad_phone = api.post(f"/campaigns/{campaign}/contacts", json=[{"phone": "123"}], headers=owner)
    assert bad_phone.status_code == 422


def test_a_number_on_the_do_not_call_list_is_kept_but_skipped_with_the_reason(
    api: TestClient, migrated_url: str
) -> None:
    employee, owner = setup_bulk(api, migrated_url)
    account = sql(migrated_url, "SELECT account_id FROM employees")
    for phone, source in (("+919876543210", "manual"), ("+919876543211", "caller_request")):
        sql(
            migrated_url,
            "INSERT INTO dnc_entries (account_id, phone, source) VALUES (:a, :p, :s)",
            {"a": account, "p": phone, "s": source},
        )
    campaign = make_campaign(
        api, owner, employee, ["9876543210", "9876543211", "9876543212"], start=False, consent=False
    )
    found = {c["phone"]: (c["status"], c["reason"]) for c in contacts(api, owner, campaign)}
    assert found == {
        "+919876543210": ("skipped", "on the do-not-call list"),
        "+919876543211": ("skipped", "asked not to be called again"),
        "+919876543212": ("pending", None),
    }


def test_turning_the_switch_off_still_skips_people_who_asked_not_to_be_called(
    api: TestClient, migrated_url: str
) -> None:
    employee, owner = setup_bulk(api, migrated_url)
    account = sql(migrated_url, "SELECT account_id FROM employees")
    for phone, source in (("+919876543210", "manual"), ("+919876543211", "caller_request")):
        sql(
            migrated_url,
            "INSERT INTO dnc_entries (account_id, phone, source) VALUES (:a, :p, :s)",
            {"a": account, "p": phone, "s": source},
        )
    campaign = make_campaign(
        api,
        owner,
        employee,
        ["9876543210", "9876543211"],
        start=False,
        consent=False,
        skip_dnc=False,
    )
    found = {c["phone"]: c["status"] for c in contacts(api, owner, campaign)}
    assert found == {"+919876543210": "pending", "+919876543211": "skipped"}


def test_the_exclusion_list_skips_uploaded_and_waiting_contacts(
    api: TestClient, migrated_url: str
) -> None:
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(
        api, owner, employee, ["9876543210", "9876543211"], start=False, consent=False
    )
    added = api.post(
        f"/campaigns/{campaign}/exclusions",
        json={"text": "9876543210\n9876543299\nnope"},
        headers=owner,
    ).json()
    assert added == {"added": 2, "invalid_count": 1}
    assert api.get(f"/campaigns/{campaign}/exclusions", headers=owner).json() == [
        "+919876543210",
        "+919876543299",
    ]
    states = {c["phone"]: c["status"] for c in contacts(api, owner, campaign)}
    assert states == {"+919876543210": "skipped", "+919876543211": "pending"}
    # Uploading an excluded number later is skipped too.
    later = api.post(
        f"/campaigns/{campaign}/contacts/import",
        json={"format": "paste", "text": "9876543299"},
        headers=owner,
    ).json()
    assert later["skipped_excluded"] == 1
    gone = api.delete(f"/campaigns/{campaign}/exclusions/+919876543299", headers=owner)
    assert gone.status_code == 200
    assert (
        api.delete(f"/campaigns/{campaign}/exclusions/+919876543299", headers=owner).status_code
        == 404
    )


def test_a_saved_list_starts_other_campaigns_with_only_the_declared_variables(
    api: TestClient, migrated_url: str
) -> None:
    employee, owner = setup_bulk(api, migrated_url, variables=("city",))
    saved = api.post(
        "/contact-lists",
        json={"name": "Pune leads", "text": CSV, "mapping": MAPPING},
        headers=owner,
    )
    assert saved.status_code == 201 and saved.json()["added"] == 2
    listing = api.get("/contact-lists", headers=owner).json()
    assert [(row["name"], row["contacts"]) for row in listing] == [("Pune leads", 2)]
    full = api.get(f"/contact-lists/{saved.json()['id']}", headers=owner).json()
    assert full["total"] == 2 and full["contacts"][0]["variables"] == {
        "city": "Pune",
        "plan": "Gold",
    }
    campaign = make_campaign(api, owner, employee, start=False, consent=False)
    used = api.post(
        f"/campaigns/{campaign}/contacts/from-list",
        json={"list_id": saved.json()["id"]},
        headers=owner,
    )
    assert used.json()["added"] == 2
    assert contacts(api, owner, campaign)[0]["variables"] == {
        "city": "Pune"
    }  # "plan" is not declared


def test_an_upload_can_be_saved_as_a_list_and_a_list_is_private_to_its_account(
    api: TestClient, migrated_url: str
) -> None:
    employee, owner = setup_bulk(api, migrated_url, variables=("city", "plan"))
    campaign = make_campaign(api, owner, employee, start=False, consent=False)
    done = import_csv(api, owner, campaign, save_as_list="Autumn")
    list_id = done.json()["list_id"]
    assert list_id and api.get(f"/contact-lists/{list_id}", headers=owner).json()["total"] == 2
    other = signup_second(api)
    assert api.get(f"/contact-lists/{list_id}", headers=other).status_code == 404
    assert api.get("/contact-lists", headers=other).json() == []
    assert api.delete(f"/contact-lists/{list_id}", headers=other).status_code == 404
    assert api.delete(f"/contact-lists/{list_id}", headers=owner).json() == {"deleted": True}
    assert len(contacts(api, owner, campaign)) == 2  # the campaign keeps its contacts


def test_contacts_cannot_be_added_to_another_accounts_or_a_finished_campaign(
    api: TestClient, migrated_url: str
) -> None:
    employee, owner = setup_bulk(api, migrated_url)
    campaign = make_campaign(api, owner, employee, ["9876543210"], start=False, consent=False)
    other = signup_second(api)
    body = {"format": "paste", "text": "9876543211"}
    assert (
        api.post(f"/campaigns/{campaign}/contacts/import", json=body, headers=other).status_code
        == 404
    )
    api.post(f"/campaigns/{campaign}/cancel", headers=owner)
    closed = api.post(f"/campaigns/{campaign}/contacts/import", json=body, headers=owner)
    assert closed.status_code == 409
