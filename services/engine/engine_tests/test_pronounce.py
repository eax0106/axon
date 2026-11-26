"""The owner's pronunciation list changes only what the voice is given, per language."""

import asyncio
import os
from typing import Any

from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.sarvam.tts import SarvamTTSService

from engine.pronounce import Pronouncer

ENTRIES = [
    ("te", "Skyline", "స్కై లైన్"),
    ("te", "డాక్టర్", "డా."),  # an Indic word is matched whole too
    ("en", "Skyline", "Sky line"),
    ("hi", "CIBIL", "सिबिल"),
    ("en", "Dr. Rao", "Doctor Raao"),
]


def test_each_language_uses_its_own_list() -> None:
    say = Pronouncer(ENTRIES).speak
    assert say("Welcome to Skyline Habitats.") == "Welcome to Sky line Habitats."
    assert say("మా Skyline ప్రాజెక్ట్") == "మా స్కై లైన్ ప్రాజెక్ట్"
    assert say("आपका CIBIL score") == "आपका सिबिल score"
    assert say("Your CIBIL score") == "Your CIBIL score"  # no English entry for it


def test_whole_words_only_and_case_does_not_matter() -> None:
    say = Pronouncer(ENTRIES).speak
    assert say("SKYLINE and skylines and Skyline's") == "Sky line and skylines and Sky line's"
    assert say("Meet Dr. Rao today") == "Meet Doctor Raao today"
    assert say("డాక్టర్‌గారు, డాక్టర్ వస్తారు") == "డాక్టర్‌గారు, డా. వస్తారు"


def test_restore_gives_back_the_owners_word() -> None:
    pronouncer = Pronouncer(ENTRIES)
    assert pronouncer.restore("మా స్కై లైన్ ప్రాజెక్ట్") == "మా Skyline ప్రాజెక్ట్"
    assert pronouncer.restore("Welcome to sky line") == "Welcome to Skyline"
    assert not Pronouncer([])  # no list, nothing attached to the call


def test_the_vendors_text_transform_applies_the_list(monkeypatch: Any) -> None:
    monkeypatch.setitem(os.environ, "SARVAM_API_KEY", "test-key")
    pronouncer = Pronouncer(ENTRIES)
    services: list[Any] = [
        SarvamTTSService(api_key="test-key"),
        CartesiaTTSService(api_key="test-key", settings=CartesiaTTSService.Settings(voice="v")),
    ]
    for service in services:
        service.add_text_transformer(pronouncer.transform)
        spoken = asyncio.run(service._transform_text("Visit Skyline now.", "sentence"))
        assert spoken is not None and spoken.startswith("Visit Sky line now.")
