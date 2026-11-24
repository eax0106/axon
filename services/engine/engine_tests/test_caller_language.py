"""The LLM is told plainly when the caller speaks another of the employee's languages."""

import asyncio

from pipecat.frames.frames import LLMMessagesAppendFrame, TranscriptionFrame
from pipecat.tests.utils import run_test

from engine.call import CallerLanguage, spoken_language


def said(text: str) -> TranscriptionFrame:
    return TranscriptionFrame(text=text, user_id="caller", timestamp="")


def notes(language: str, allowed: set[str], *texts: str) -> list[str]:
    down, _ = asyncio.run(
        run_test(CallerLanguage(language, allowed), frames_to_send=[said(t) for t in texts])
    )
    appended = [m for f in down if isinstance(f, LLMMessagesAppendFrame) for m in f.messages]
    return [str(m["content"]) for m in appended]  # type: ignore[index]


def test_it_reads_the_language_from_the_script() -> None:
    assert spoken_language("Hi, what are your clinic timings on Saturday?") == "en"
    assert spoken_language("శనివారం క్లినిక్ టైమింగ్స్ ఏంటి?") == "te"
    assert spoken_language("शनिवार को क्लिनिक कब खुलता है?") == "hi"
    assert spoken_language("Hello") is None  # too short to switch on


def test_english_words_inside_telugu_or_hindi_do_not_make_it_english() -> None:
    # Real Sarvam transcripts of code-mixed callers: the English words come back in Latin script.
    assert spoken_language("మీ clinic timings ఏంటి?") == "te"
    assert spoken_language("రేపు appointment book చేయగలరా?") == "te"
    assert spoken_language("क्या मैं कल का appointment book कर सकता हूँ?") == "hi"
    assert notes("te", {"te", "en"}, "Do you open on Saturday?", "మీ clinic timings ఏంటి?") == [
        "The caller is speaking English. Reply only in English from now on.",
        "The caller is speaking Telugu. Reply only in Telugu from now on.",
    ]


def test_an_english_caller_to_a_telugu_employee_is_answered_in_english() -> None:
    assert notes("te", {"te", "en"}, "Hi, what are your clinic timings on Saturday?") == [
        "The caller is speaking English. Reply only in English from now on."
    ]


def test_nothing_is_said_while_the_caller_keeps_to_one_language() -> None:
    assert notes("te", {"te", "en"}, "శనివారం క్లినిక్ టైమింగ్స్ ఏంటి?") == []
    assert notes("te", {"te", "en"}, "Do you open on Saturday?", "And on Sunday morning?") == [
        "The caller is speaking English. Reply only in English from now on."
    ]


def test_a_language_the_employee_does_not_speak_is_not_followed() -> None:
    assert notes("te", {"te", "en"}, "शनिवार को क्लिनिक कब खुलता है?") == []
