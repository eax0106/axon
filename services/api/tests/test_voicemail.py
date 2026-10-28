"""A call is voicemail only when the transcript shows the recording in its own words."""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.calls import analysis

from .conftest import sql
from .test_post_call_analysis import NOW, TURNS, reply, run
from .test_post_call_job import api, make_call, model_reply, process, row, setup  # noqa: F401

MACHINE: list[dict[str, Any]] = [
    {"role": "assistant", "text": "Hello, this is Asha from SunBright Solar."},
    {
        "role": "user",
        "text": "The person you called is not available. Please leave a message after the tone",
    },
]
QUOTE = "please leave a message after the tone"


def test_a_recorded_greeting_quoted_from_the_caller_side_is_voicemail() -> None:
    result = run(reply(voicemail={"detected": True, "quote": QUOTE}), MACHINE)
    assert result.voicemail is True


@pytest.mark.parametrize(
    ("said", "why"),
    [
        ({"detected": True, "quote": "leave your name and number"}, "quote not in the call"),
        ({"detected": True, "quote": None}, "no quote"),
        ({"detected": True, "quote": "tone"}, "quote too short to prove anything"),
        ({"detected": True, "quote": "Hello, this is Asha from SunBright Solar."}, "agent's words"),
        ({"detected": False, "quote": QUOTE}, "the model says it is not"),
        ({"detected": "yes", "quote": QUOTE}, "not a real true"),
        ("voicemail", "wrong shape"),
        (None, "nothing said"),
    ],
)
def test_without_the_recordings_own_words_it_is_not_voicemail(said: Any, why: str) -> None:
    assert run(reply(voicemail=said), MACHINE).voicemail is False, why


def test_a_reply_that_never_mentions_voicemail_means_no() -> None:
    assert run(reply(), MACHINE).voicemail is False
    assert (
        run(reply(voicemail={"detected": True, "quote": QUOTE}), TURNS).voicemail is False
    )  # a person talked


def test_the_prompt_tells_the_model_what_voicemail_is() -> None:
    assert "voicemail" in analysis.SYSTEM and "answering machine" in analysis.SYSTEM


def test_the_job_keeps_the_flag_on_the_call_and_a_person_stays_false(
    api: tuple[TestClient, Any],  # noqa: F811
    migrated_url: str,
) -> None:
    client, gemini = api
    employee, _ = setup(client, migrated_url)
    machine = make_call(migrated_url, employee, MACHINE, phone="+919876543211")
    person = make_call(migrated_url, employee, phone="+919876543212")

    gemini.text = model_reply(voicemail={"detected": True, "quote": QUOTE})
    process(migrated_url, NOW)
    assert row(migrated_url, machine, "voicemail") is True

    gemini.text = model_reply(voicemail={"detected": True, "quote": "no such words in the call"})
    sql(migrated_url, "UPDATE calls SET analysis_status = 'pending' WHERE id = :c", {"c": person})
    process(migrated_url, NOW)
    assert row(migrated_url, person, "voicemail") is False
    assert json.loads(gemini.requests[0].content)  # the model really was asked
