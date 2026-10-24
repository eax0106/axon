"""The engine runs a call on the employee's own script, voice row and delivery settings."""

import asyncio
import struct
import wave
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.sarvam.tts import SarvamTTSService
from pipecat.services.smallest.tts import SmallestTTSService
from sqlalchemy.ext.asyncio import create_async_engine
from tests.helpers import seed, signup

from app.providers.base import ProviderNotConfiguredError
from app.providers.registry import VENDOR_KEYS
from engine.ambience import mixer_for
from engine.legs import voice_legs
from engine.main import _NoPlanError, _setup
from engine.main import app as engine_app
from engine.plan import load_plan

PUBLIC = "https://engine.example.in"


@pytest.fixture
def api(
    db_client: TestClient, migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    seed(migrated_url)
    for vendors in VENDOR_KEYS.values():
        for keys in vendors.values():
            for key in keys:
                monkeypatch.setenv(key, "test-key")
    monkeypatch.setenv("CARTESIA_VOICE_HI", "voice-hi")
    monkeypatch.setenv("CARTESIA_VOICE_TE", "voice-te")
    monkeypatch.setenv("AXON_ENGINE_PUBLIC_URL", PUBLIC)
    yield db_client


def run(url: str, work: Any) -> Any:
    """Run `work(app_like)` with a database engine on a fresh event loop."""

    async def go() -> Any:
        engine = create_async_engine(url)
        try:
            return await work(SimpleNamespace(state=SimpleNamespace(db=engine)))
        finally:
            await engine.dispose()

    return asyncio.run(go())


def hire(api: TestClient, owner: dict[str, str], **fields: Any) -> dict[str, Any]:
    body = {"channel": "instant", "name": "Asha", "language": "te", **fields}
    created: dict[str, Any] = api.post("/employees", json=body, headers=owner).json()
    return created


def pick_voice(api: TestClient, owner: dict[str, str], tier: str, language: str) -> dict[str, Any]:
    voices: list[dict[str, Any]] = api.get(
        f"/voices?tier={tier}&language={language}", headers=owner
    ).json()
    return voices[0]


def test_a_live_call_uses_the_published_script_not_the_draft(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    employee = hire(api, owner)
    path = f"/employees/{employee['id']}"
    api.put(path + "/script", json={"welcome_message": "Published hello"}, headers=owner)
    api.post(path + "/publish", headers=owner)
    api.put(path + "/script", json={"welcome_message": "Unpublished edit"}, headers=owner)

    plan = run(migrated_url, lambda a: load_plan(a.state.db, employee["id"]))
    assert "Published hello" in plan.system_prompt and "Unpublished edit" not in plan.system_prompt
    assert plan.language == "te" and plan.voice is not None and plan.tts_speed == 1.0


def test_nothing_published_means_no_plan_unless_it_is_a_test_call(
    api: TestClient, migrated_url: str
) -> None:
    from tests.conftest import sql

    owner = signup(api)
    employee = hire(api, owner)
    api.put(
        f"/employees/{employee['id']}/script",
        json={"welcome_message": "Draft hello"},
        headers=owner,
    )
    assert run(migrated_url, lambda a: load_plan(a.state.db, employee["id"])) is None

    web = api.post(f"/employees/{employee['id']}/web-test-call", headers=owner).json()
    plan = run(migrated_url, lambda a: load_plan(a.state.db, employee["id"], web["call_id"]))
    assert plan is not None and "Draft hello" in plan.system_prompt
    # The draft is reachable only through a test-call row of the same employee.
    other = hire(api, owner, name="Other")
    assert run(migrated_url, lambda a: load_plan(a.state.db, other["id"], web["call_id"])) is None
    sql(migrated_url, "UPDATE calls SET is_test = false")
    assert (
        run(migrated_url, lambda a: load_plan(a.state.db, employee["id"], web["call_id"])) is None
    )


def test_unknown_or_malformed_ids_have_no_plan(api: TestClient, migrated_url: str) -> None:
    for bad in ("", "not-a-uuid", "00000000-0000-0000-0000-000000000000"):
        assert run(migrated_url, lambda a, b=bad: load_plan(a.state.db, b)) is None


def test_the_tts_is_built_from_the_employees_voice_row_and_speed(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    cases = [
        ("value", "te", SarvamTTSService, "sarvam"),
        ("standard", "te", SmallestTTSService, "smallest"),
        ("premium", "en", CartesiaTTSService, "cartesia"),
    ]
    for tier, language, service, provider in cases:
        voice = pick_voice(api, owner, tier, language)
        employee = hire(api, owner, language=language, voice_id=voice["id"])
        path = f"/employees/{employee['id']}"
        api.put(path + "/settings", json={"tts_speed": 1.25}, headers=owner)
        api.post(path + "/publish", headers=owner)

        async def build(a: Any, eid: str = employee["id"]) -> Any:
            plan = await load_plan(a.state.db, eid)
            assert plan is not None
            return plan, voice_legs(plan.language, voice=plan.voice, speed=plan.tts_speed)

        plan, (_, _, tts) = run(migrated_url, build)
        assert (
            isinstance(tts, service) and plan.voice is not None and plan.voice.provider == provider
        )
        assert tts._settings.voice == plan.voice.provider_voice_id
        settings = tts._settings
        if provider == "sarvam":
            assert settings.pace == 1.25
        elif provider == "smallest":
            assert settings.speed == 1.25
        else:
            assert settings.generation_config.speed == 1.25


def test_setup_gives_the_call_the_employees_prompt_language_and_ambience(
    api: TestClient, migrated_url: str
) -> None:
    owner = signup(api)
    employee = hire(api, owner, language="hi", name="Meera")
    path = f"/employees/{employee['id']}"
    api.put(
        path + "/script",
        json={"welcome_message": "Namaste", "end_rules": "Stop if busy."},
        headers=owner,
    )
    api.put(path + "/settings", json={"ambience": "office", "ambience_volume": 0.5}, headers=owner)
    api.post(path + "/publish", headers=owner)

    legs, settings = run(migrated_url, lambda a: _setup(a, "en", employee["id"], ""))
    assert len(legs) == 3 and settings.language == "hi"
    assert "You are Meera" in settings.system_prompt and "Namaste" in settings.system_prompt
    assert (settings.ambience, settings.ambience_volume) == ("office", 0.5)


def test_setup_without_an_employee_keeps_the_plain_defaults(
    api: TestClient, migrated_url: str
) -> None:
    legs, settings = run(migrated_url, lambda a: _setup(a, "te", "", ""))
    assert len(legs) == 3 and settings.language == "te" and settings.system_prompt == ""


def test_setup_for_an_unpublished_employee_is_refused(api: TestClient, migrated_url: str) -> None:
    employee = hire(api, signup(api))
    with pytest.raises(_NoPlanError):
        run(migrated_url, lambda a: _setup(a, "en", employee["id"], ""))


def test_a_voice_whose_vendor_has_no_key_is_503(
    api: TestClient, migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = signup(api)
    voice = pick_voice(api, owner, "premium", "en")
    employee = hire(api, owner, language="en", voice_id=voice["id"])
    api.post(f"/employees/{employee['id']}/publish", headers=owner)
    monkeypatch.delenv("CARTESIA_API_KEY")
    with pytest.raises(ProviderNotConfiguredError) as raised:
        run(migrated_url, lambda a: _setup(a, "en", employee["id"], ""))
    assert raised.value.missing_keys == ["CARTESIA_API_KEY"]


def test_answer_url_and_stream_url_carry_the_employee(api: TestClient, migrated_url: str) -> None:
    owner = signup(api)
    employee = hire(api, owner, language="hi")
    api.post(f"/employees/{employee['id']}/publish", headers=owner)
    with TestClient(engine_app) as engine:
        engine_app.state.db = create_async_engine(migrated_url)
        missing = engine.post("/vobiz/answer?employee=" + str(uuid_zero()))
        assert missing.status_code == 404
        ok = engine.post(f"/vobiz/answer?employee={employee['id']}")
    assert ok.status_code == 200
    assert f"employee={employee['id']}" in ok.text and "lang=hi" in ok.text


def uuid_zero() -> str:
    return "00000000-0000-0000-0000-000000000000"


def silent_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as clip:
        clip.setnchannels(1)
        clip.setsampwidth(2)
        clip.setframerate(16000)
        clip.writeframes(struct.pack("<h", 0) * 1600)


def test_ambience_mixer_exists_only_when_the_sound_file_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AXON_AMBIENCE_DIR", str(tmp_path))
    assert mixer_for("none", 0.3) is None
    assert mixer_for("office", 0.3) is None  # no file dropped in yet: no background sound
    silent_wav(tmp_path / "office.wav")
    assert mixer_for("office", 0.3) is not None
