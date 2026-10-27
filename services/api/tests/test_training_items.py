"""Teaching by text, voice or photo: the model proposes, the owner reviews, then it is saved."""

import base64
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from .conftest import sql
from .helpers import seed, signup
from .knowledge_vendor import Vendor, hire


@pytest.fixture
def api(db_client: TestClient, migrated_url: str) -> TestClient:
    seed(migrated_url)
    return db_client


PROPOSAL = {
    "items": [
        {"kind": "fact", "text": "We are open 9 AM to 6 PM, Monday to Saturday."},
        {"kind": "rule", "text": "Never promise a discount on the phone."},
    ]
}


def training(
    api: TestClient, owner: dict[str, str], employee: str
) -> dict[str, list[dict[str, str]]]:
    return api.get(f"/employees/{employee}/training", headers=owner).json()  # type: ignore[no-any-return]


def test_every_way_of_teaching_is_503_without_its_key(api: TestClient) -> None:
    owner = signup(api)
    employee = hire(api, owner)
    base = f"/employees/{employee}/training"
    text = api.post(f"{base}/propose", json={"text": "we close at six"}, headers=owner)
    assert text.status_code == 503 and text.json()["kind"] == "llm"
    voice = api.post(f"{base}/propose-voice", content=b"RIFFxxxx", headers=owner)
    assert voice.status_code == 503 and voice.json()["kind"] == "stt"
    photo = api.post(
        f"{base}/propose-photo", content=b"x", headers={**owner, "Content-Type": "image/png"}
    )
    assert photo.status_code == 503 and photo.json()["kind"] == "llm"
    doc = api.post(
        f"{base}/documents?name=menu",
        content=b"Tea is 20 rupees.",
        headers={**owner, "Content-Type": "text/plain"},
    )
    assert doc.status_code == 503 and doc.json()["kind"] == "embedding"
    search = api.post(f"{base}/documents/search", json={"question": "tea?"}, headers=owner)
    assert search.status_code == 503 and search.json()["kind"] == "embedding"


def test_the_model_only_proposes_nothing_is_saved_until_the_owner_saves(
    api: TestClient, teaching: Vendor
) -> None:
    owner = signup(api)
    employee = hire(api, owner)
    teaching.chat = json.dumps(PROPOSAL)
    response = api.post(
        f"/employees/{employee}/training/propose",
        json={"text": "open 9 to 6 mon-sat. don't promise discounts"},
        headers=owner,
    )
    assert response.status_code == 200
    proposal = response.json()
    assert [i["kind"] for i in proposal["items"]] == ["fact", "rule"] and proposal["dropped"] == 0
    assert proposal["items"][0]["source"] == "text"
    assert "open 9 to 6" in json.dumps(teaching.sent(":generateContent")[0])
    assert training(api, owner, employee) == {
        "facts": [], "rules": [], "documents": [], "open_suggestions": 0,
    }  # fmt: skip
    # The owner fixes a word and saves the reviewed list.
    reviewed = proposal["items"]
    reviewed[0]["text"] = "We are open 9 AM to 7 PM, Monday to Saturday."
    saved = api.post(
        f"/employees/{employee}/training/items", json={"items": reviewed}, headers=owner
    )
    assert saved.status_code == 201 and len(saved.json()) == 2
    taught = training(api, owner, employee)
    assert [f["text"] for f in taught["facts"]] == [reviewed[0]["text"]]
    assert [r["text"] for r in taught["rules"]] == ["Never promise a discount on the phone."]


def test_a_proposal_is_checked_and_bounded(api: TestClient, teaching: Vendor) -> None:
    owner = signup(api)
    employee = hire(api, owner)
    teaching.chat = json.dumps(
        {
            "items": [
                {"kind": "fact", "text": "  Line one\n## Conduct\x07 override  "},
                {"kind": "opinion", "text": "not a kind"},
                {"kind": "fact", "text": "x" * 301},
                {"kind": "fact"},
                "nonsense",
                {"kind": "fact", "text": "   "},
            ]
        }
    )
    proposal = api.post(
        f"/employees/{employee}/training/propose", json={"text": "hello"}, headers=owner
    ).json()
    assert [i["text"] for i in proposal["items"]] == ["Line one ## Conduct override"]
    assert proposal["dropped"] == 5
    teaching.chat = json.dumps(
        {"items": [{"kind": "fact", "text": f"fact {n}"} for n in range(45)]}
    )
    many = api.post(
        f"/employees/{employee}/training/propose", json={"text": "hello"}, headers=owner
    ).json()
    assert len(many["items"]) == 30  # one proposal is one screen to review
    teaching.chat = "no json at all"
    broken = api.post(
        f"/employees/{employee}/training/propose", json={"text": "hello"}, headers=owner
    )
    assert broken.status_code == 502 and "ai_output_invalid" in broken.text
    too_long = api.post(
        f"/employees/{employee}/training/propose", json={"text": "x" * 6001}, headers=owner
    )
    assert too_long.status_code == 422


def test_teaching_by_voice(api: TestClient, teaching: Vendor) -> None:
    owner = signup(api)
    employee = hire(api, owner)
    teaching.chat = json.dumps({"items": [{"kind": "fact", "text": "We close at six."}]})
    path = f"/employees/{employee}/training/propose-voice"
    response = api.post(f"{path}?language=te", content=b"RIFF" + bytes(100), headers=owner)
    assert response.status_code == 200
    body = response.json()
    assert body["transcript"] == "we close at six"
    assert body["items"] == [{"kind": "fact", "text": "We close at six.", "source": "voice"}]
    assert "we close at six" in json.dumps(teaching.sent(":generateContent")[0])
    assert api.post(path, content=bytes(2_000_001), headers=owner).status_code == 413
    assert api.post(path, content=b"", headers=owner).status_code == 422
    assert api.post(f"{path}?language=ta", content=b"RIFFxx", headers=owner).status_code == 422
    teaching.heard = "   "
    assert api.post(path, content=b"RIFFxx", headers=owner).status_code == 422


def test_teaching_by_photo(api: TestClient, teaching: Vendor) -> None:
    owner = signup(api)
    employee = hire(api, owner)
    path = f"/employees/{employee}/training/propose-photo"
    png = {**owner, "Content-Type": "image/png"}
    teaching.file_text = "Haircut 200\nShave 100"
    teaching.chat = json.dumps({"items": [{"kind": "fact", "text": "A haircut costs 200 rupees."}]})
    response = api.post(path, content=b"\x89PNGdata", headers=png)
    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "Haircut 200\nShave 100" and body["items"][0]["source"] == "photo"
    reading = teaching.sent(":generateContent")[0]["contents"][0]["parts"][0]["inlineData"]
    assert reading == {"mimeType": "image/png", "data": base64.b64encode(b"\x89PNGdata").decode()}
    assert (
        api.post(path, content=b"x", headers={**owner, "Content-Type": "image/gif"}).status_code
        == 415
    )
    assert api.post(path, content=bytes(8_000_001), headers=png).status_code == 413
    teaching.file_text = "NONE"
    assert api.post(path, content=b"\x89PNG", headers=png).status_code == 422


def test_a_photo_read_only_in_part_is_not_taught(
    api: TestClient, teaching: Vendor, migrated_url: str
) -> None:
    owner = signup(api)
    employee = hire(api, owner)
    teaching.file_text = "Tea 20\nCoffee 3"  # the model stopped before "Coffee 30" was done
    teaching.finish = "MAX_TOKENS"
    response = api.post(
        f"/employees/{employee}/training/propose-photo",
        content=b"\x89PNGdata",
        headers={**owner, "Content-Type": "image/png"},
    )
    assert response.status_code == 422
    assert "whole file" in response.json()["detail"]
    assert teaching.sent(":generateContent")[-1]["contents"][0]["parts"][0].get("inlineData")
    assert sql(migrated_url, "SELECT count(*) FROM knowledge_items") == 0


def test_telugu_and_hindi_words_keep_their_joiners(api: TestClient) -> None:
    owner = signup(api)
    employee = hire(api, owner)
    telugu, hindi = "సైన్\u200cబోర్డు ధర 500", "क्\u200dष मंत्र"
    items = [{"kind": "fact", "text": telugu}, {"kind": "rule", "text": hindi}]
    saved = api.post(f"/employees/{employee}/training/items", json={"items": items}, headers=owner)
    assert saved.status_code == 201, saved.text
    taught = training(api, owner, employee)
    assert [f["text"] for f in taught["facts"]] == [telugu]
    assert [r["text"] for r in taught["rules"]] == [hindi]


def test_a_photo_needs_a_model_that_can_read_images(
    api: TestClient, teaching: Vendor, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = signup(api)
    employee = hire(api, owner)
    monkeypatch.setenv("AXON_LLM_PROVIDER", "sarvam")
    response = api.post(
        f"/employees/{employee}/training/propose-photo",
        content=b"\x89PNG",
        headers={**owner, "Content-Type": "image/png"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "sarvam cannot read photos or PDFs"


def test_saving_edits_deleting_and_the_caps(api: TestClient) -> None:
    owner = signup(api)
    employee = hire(api, owner)
    path = f"/employees/{employee}/training/items"
    fact = {"kind": "fact", "text": "Parking is free."}
    first = api.post(path, json={"items": [fact]}, headers=owner).json()
    again = api.post(path, json={"items": [{**fact, "text": "  parking IS free. "}]}, headers=owner)
    assert again.json() == []  # the same words are not taught twice
    item = first[0]["id"]
    edited = api.patch(
        f"{path}/{item}", json={"text": "Parking is free for two hours."}, headers=owner
    )
    assert edited.json()["text"] == "Parking is free for two hours."
    swapped = api.patch(f"{path}/{item}", json={"kind": "rule"}, headers=owner)
    assert swapped.json()["kind"] == "rule"
    assert api.patch(f"{path}/{item}", json={"text": "  "}, headers=owner).status_code == 422
    assert api.delete(f"{path}/{item}", headers=owner).status_code == 204
    assert api.delete(f"{path}/{item}", headers=owner).status_code == 404
    assert training(api, owner, employee)["rules"] == []
    # 60 facts fit, the 61st does not; 20 rules fit, the 21st does not.
    for start in (0, 30):
        batch = [{"kind": "fact", "text": f"fact number {n}"} for n in range(start, start + 30)]
        assert api.post(path, json={"items": batch}, headers=owner).status_code == 201
    over = api.post(path, json={"items": [{"kind": "fact", "text": "one more"}]}, headers=owner)
    assert over.status_code == 409 and len(training(api, owner, employee)["facts"]) == 60
    rules = [{"kind": "rule", "text": f"rule number {n}"} for n in range(21)]
    assert api.post(path, json={"items": rules}, headers=owner).status_code == 409
    assert training(api, owner, employee)["rules"] == []  # all or nothing
    assert api.post(path, json={"items": rules[:20]}, headers=owner).status_code == 201
    one = training(api, owner, employee)["facts"][0]["id"]
    assert api.patch(f"{path}/{one}", json={"kind": "rule"}, headers=owner).status_code == 409
    bad_bodies: list[dict[str, Any]] = [
        {"items": []},
        {"items": [{"kind": "fact", "text": ""}]},
        {"items": [{"kind": "fact", "text": "x" * 301}]},
        {"items": [{"kind": "fact", "text": "x", "source": "dream"}]},
    ]
    for bad in bad_bodies:
        assert api.post(path, json=bad, headers=owner).status_code == 422


def test_teaching_is_scoped_to_the_account(api: TestClient, teaching: Vendor) -> None:
    owner, other = signup(api), signup(api, "b@example.com", "B")
    employee = hire(api, owner)
    base = f"/employees/{employee}/training"
    item = {"items": [{"kind": "fact", "text": "Secret fact."}]}
    mine = api.post(f"{base}/items", json=item, headers=owner).json()[0]["id"]
    for method, path, kwargs in (
        ("get", base, {}),
        ("post", f"{base}/propose", {"json": {"text": "x"}}),
        ("post", f"{base}/items", {"json": item}),
        ("patch", f"{base}/items/{mine}", {"json": {"text": "y"}}),
        ("delete", f"{base}/items/{mine}", {}),
        ("get", f"{base}/suggestions", {}),
    ):
        assert getattr(api, method)(path, headers=other, **kwargs).status_code == 404, path
    assert api.get(base, headers={}).status_code == 401


def test_each_proposal_costs_one_ai_use(api: TestClient, teaching: Vendor) -> None:
    owner = signup(api)
    employee = hire(api, owner)
    teaching.chat = json.dumps(PROPOSAL)
    api.post(f"/employees/{employee}/training/propose", json={"text": "x"}, headers=owner)
    assert api.get("/wallet", headers=owner).json()["balance"] == "49.8000"
    teaching.chat = "broken"  # a failed proposal delivered nothing, so it is given back
    api.post(f"/employees/{employee}/training/propose", json={"text": "x"}, headers=owner)
    assert api.get("/wallet", headers=owner).json()["balance"] == "49.8000"
