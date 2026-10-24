import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.employees.ai import AiOutputError, parse_json
from app.providers.speech import common

from .helpers import seed, signup


@pytest.fixture
def api(db_client: TestClient, migrated_url: str) -> TestClient:
    seed(migrated_url)
    return db_client


class Vendor:
    """Gemini answers every request with `text`; the requests it received are kept."""

    def __init__(self) -> None:
        self.text = "{}"
        self.status = 200
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "api.sarvam.ai":
            return httpx.Response(
                200, json={"request_id": "r", "transcript": "  I sell solar panels "}
            )
        payload = {"candidates": [{"content": {"role": "model", "parts": [{"text": self.text}]}}]}
        return httpx.Response(self.status, json=payload)


@pytest.fixture
def vendor(monkeypatch: pytest.MonkeyPatch) -> Iterator[Vendor]:
    for key in ("GEMINI_API_KEY", "SARVAM_API_KEY"):
        monkeypatch.setenv(key, "test-key")
    monkeypatch.setenv("AXON_STT_PROVIDER", "sarvam")
    fake = Vendor()
    transport = httpx.MockTransport(fake.handler)
    monkeypatch.setattr(
        common.VendorHealth,
        "client",
        lambda self, timeout=60.0: httpx.AsyncClient(transport=transport),
    )
    yield fake


def hire(api: TestClient, headers: dict[str, str]) -> str:
    response = api.post("/employees", json={"channel": "instant", "name": "Asha"}, headers=headers)
    return str(response.json()["id"])


BRIEF = {"brief": "Call new leads from my solar business.", "channel": "instant", "language": "en"}
DRAFT = {
    "name": "Meera",
    "role_title": "Solar advisor",
    "welcome_message": "Hi, this is Meera from SunBright.",
    "agent_information": "SunBright installs rooftop solar.",
    "sections": [{"title": "Ask the roof size", "body": "Ask how big the roof is."}],
    "end_rules": "End after booking a visit.",
    "faq": [{"question": "Is there a subsidy?", "answer": "Yes, we help with the paperwork."}],
    "capture": [{"name": "roof_size", "description": "Roof area in square feet"}],
}


def test_every_ai_endpoint_is_503_without_keys(api: TestClient) -> None:
    owner = signup(api)
    employee = hire(api, owner)
    calls = [
        ("/ai/brief-questions", BRIEF),
        ("/ai/draft-agent", BRIEF),
        ("/ai/structure-prompt", {"text": "hello"}),
        (f"/employees/{employee}/ai/edit-flow", {"instruction": "shorter"}),
        (f"/employees/{employee}/chat", {"messages": [{"role": "user", "content": "hi"}]}),
    ]
    for path, body in calls:
        response = api.post(path, json=body, headers=owner)
        assert response.status_code == 503, path
        assert (
            response.json()["error"] == "provider_not_configured"
            and response.json()["kind"] == "llm"
        )
    response = api.post("/ai/transcribe-chunk?language=te", content=b"RIFFxxxx", headers=owner)
    assert response.status_code == 503 and response.json()["kind"] == "stt"


def test_brief_questions_parses_a_fenced_reply(api: TestClient, vendor: Vendor) -> None:
    owner = signup(api)
    vendor.text = '```json\n{"questions": ["Which cities?", "What is the subsidy?"]}\n```'
    response = api.post("/ai/brief-questions", json=BRIEF, headers=owner)
    assert response.json() == {"questions": ["Which cities?", "What is the subsidy?"]}
    sent = json.loads(vendor.requests[0].content)
    assert "Read the owner's brief" in sent["systemInstruction"]["parts"][0]["text"]
    assert "solar business" in sent["contents"][0]["parts"][0]["text"]


def test_malformed_model_output_is_a_502_not_a_crash(api: TestClient, vendor: Vendor) -> None:
    owner = signup(api)
    for text in (
        "no json here",
        '{"questions": "nope"}',
        '{"questions": ["a","b","c","d","e","f"]}',
        "{broken",
    ):
        vendor.text = text
        response = api.post("/ai/brief-questions", json=BRIEF, headers=owner)
        assert response.status_code == 502 and "ai_output_invalid" in response.text, text


def test_draft_agent_returns_a_script_ready_to_save(api: TestClient, vendor: Vendor) -> None:
    owner = signup(api)
    vendor.text = json.dumps(DRAFT)
    body = {**BRIEF, "answers": [{"question": "Which cities?", "answer": "Hyderabad"}]}
    draft = api.post("/ai/draft-agent", json=body, headers=owner).json()
    assert draft["name"] == "Meera" and draft["role_title"] == "Solar advisor"
    assert draft["script"]["sections"][0]["title"] == "Ask the roof size"
    assert draft["script"]["sections"][0]["id"]  # ids are assigned
    assert draft["script"]["faq"][0]["question"] == "Is there a subsidy?"
    assert draft["capture"] == [{"name": "roof_size", "description": "Roof area in square feet"}]
    assert (
        "Q: Which cities?\nA: Hyderabad"
        in json.loads(vendor.requests[0].content)["contents"][0]["parts"][0]["text"]
    )
    # What the draft returns is a valid script: the client can PUT it as is.
    employee = hire(api, owner)
    assert (
        api.put(f"/employees/{employee}/script", json=draft["script"], headers=owner).status_code
        == 200
    )


def test_draft_with_a_bad_shape_is_a_502(api: TestClient, vendor: Vendor) -> None:
    owner = signup(api)
    for broken in (
        {**DRAFT, "sections": [{"title": "", "body": "x"}]},
        {**DRAFT, "capture": [{"name": "Bad Name", "description": "d"}]},
        {**DRAFT, "sections": "x"},
    ):
        vendor.text = json.dumps(broken)
        assert api.post("/ai/draft-agent", json=BRIEF, headers=owner).status_code == 502


def test_structure_prompt_splits_pasted_text(api: TestClient, vendor: Vendor) -> None:
    owner = signup(api)
    vendor.text = json.dumps(
        {k: DRAFT[k] for k in ("welcome_message", "sections", "end_rules", "faq")}
    )
    script = api.post(
        "/ai/structure-prompt", json={"text": "Say hi then ask roof size."}, headers=owner
    ).json()
    assert script["welcome_message"].startswith("Hi") and script["strictness"] == 3


def test_edit_flow_proposes_without_saving_and_keeps_protected_fields(
    api: TestClient, vendor: Vendor
) -> None:
    owner = signup(api)
    employee = hire(api, owner)
    api.put(
        f"/employees/{employee}/script",
        json={"strictness": 5, "pre_call_variables": ["lead_name"], "welcome_message": "old"},
        headers=owner,
    )
    vendor.text = json.dumps(
        {"welcome_message": "new", "strictness": 1, "pre_call_variables": [], "sections": []}
    )
    proposal = api.post(
        f"/employees/{employee}/ai/edit-flow", json={"instruction": "change welcome"}, headers=owner
    ).json()
    assert proposal["welcome_message"] == "new"
    assert proposal["strictness"] == 5 and proposal["pre_call_variables"] == ["lead_name"]
    assert (
        api.get(f"/employees/{employee}", headers=owner).json()["script"]["welcome_message"]
        == "old"
    )


def test_chat_runs_on_the_compiled_prompt_and_maps_roles(api: TestClient, vendor: Vendor) -> None:
    owner = signup(api)
    employee = hire(api, owner)
    api.put(
        f"/employees/{employee}/script",
        json={"welcome_message": "Hello from SunBright"},
        headers=owner,
    )
    vendor.text = "  Sure, tell me your roof size.  "
    body = {
        "messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "I want solar"},
        ]
    }
    assert api.post(f"/employees/{employee}/chat", json=body, headers=owner).json() == {
        "reply": "Sure, tell me your roof size."
    }
    sent = json.loads(vendor.requests[0].content)
    system = sent["systemInstruction"]["parts"][0]["text"]
    assert "Hello from SunBright" in system and "text chat" in system
    assert [c["role"] for c in sent["contents"]] == ["user", "model", "user"]


def test_chat_rules(api: TestClient, vendor: Vendor) -> None:
    owner, other = signup(api), signup(api, "b@example.com", "B")
    employee = hire(api, owner)
    path = f"/employees/{employee}/chat"
    ending_with_bot = {"messages": [{"role": "assistant", "content": "hello"}]}
    assert api.post(path, json=ending_with_bot, headers=owner).status_code == 422
    assert api.post(path, json={"messages": []}, headers=owner).status_code == 422
    live = {"messages": [{"role": "user", "content": "hi"}], "source": "live"}
    assert api.post(path, json=live, headers=owner).status_code == 409  # nothing published
    assert (
        api.post(
            path, json={"messages": [{"role": "user", "content": "hi"}]}, headers=other
        ).status_code
        == 404
    )


def test_transcribe_chunk_returns_trimmed_text_and_limits_size(
    api: TestClient, vendor: Vendor
) -> None:
    owner = signup(api)
    wav = b"RIFF" + bytes(100)
    response = api.post("/ai/transcribe-chunk?language=en", content=wav, headers=owner)
    assert response.json() == {"text": "I sell solar panels"}
    assert (
        api.post("/ai/transcribe-chunk", content=bytes(2_000_001), headers=owner).status_code == 413
    )
    assert api.post("/ai/transcribe-chunk", content=b"", headers=owner).status_code == 422
    assert (
        api.post("/ai/transcribe-chunk?language=ta", content=wav, headers=owner).status_code == 422
    )


def test_a_vendor_error_is_a_502_provider_error(api: TestClient, vendor: Vendor) -> None:
    owner = signup(api)
    vendor.status = 403
    response = api.post("/ai/brief-questions", json=BRIEF, headers=owner)
    assert response.status_code == 502
    assert response.json() == {
        "error": "provider_error",
        "vendor_status": 403,
        "detail": "HTTPStatusError calling generativelanguage.googleapis.com",
    }


def test_ai_endpoints_need_a_login(api: TestClient) -> None:
    assert api.post("/ai/brief-questions", json=BRIEF).status_code == 401


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('Here you go: {"a": {"b": 2}} done', {"a": {"b": 2}}),
    ],
)
def test_parse_json_accepts_what_models_actually_send(text: str, expected: dict[str, Any]) -> None:
    assert parse_json(text) == expected


@pytest.mark.parametrize("text", ["", "[1, 2]", "{nope", "plain words"])
def test_parse_json_rejects_the_rest(text: str) -> None:
    with pytest.raises(AiOutputError):
        parse_json(text)


def test_the_ai_endpoints_share_a_per_account_hourly_budget(
    api: TestClient, vendor: Vendor, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.employees import limits

    monkeypatch.setattr(limits, "AI_PER_HOUR", 3)
    owner, other = signup(api), signup(api, "b@example.com", "B")
    employee = hire(api, owner)
    vendor.text = '{"questions": ["Which cities?"]}'
    assert api.post("/ai/brief-questions", json=BRIEF, headers=owner).status_code == 200
    chat = {"messages": [{"role": "user", "content": "hi"}]}
    vendor.text = "ok"
    assert api.post(f"/employees/{employee}/chat", json=chat, headers=owner).status_code == 200
    assert (
        api.post("/ai/transcribe-chunk", content=b"RIFF" + bytes(10), headers=owner).status_code
        == 200
    )
    # Fourth call in the hour, whichever endpoint: refused before any vendor call.
    sent = len(vendor.requests)
    for blocked in (
        api.post("/ai/brief-questions", json=BRIEF, headers=owner),
        api.post(f"/employees/{employee}/chat", json=chat, headers=owner),
        api.post("/ai/draft-agent", json=BRIEF, headers=owner),
    ):
        assert blocked.status_code == 429
    assert len(vendor.requests) == sent
    vendor.text = '{"questions": ["Which cities?"]}'
    assert api.post("/ai/brief-questions", json=BRIEF, headers=other).status_code == 200
