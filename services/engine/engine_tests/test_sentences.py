"""TTS speaks one sentence at a time. Pipecat's sentence splitter (used by every TTS service's
default text aggregator) already knows the Indic danda; these tests pin the behaviour we rely on
for Telugu, Hindi and English."""

import asyncio

import pytest
from pipecat.utils.string import match_endofsentence
from pipecat.utils.text.simple_text_aggregator import SimpleTextAggregator


@pytest.mark.parametrize(
    ("text", "first"),
    [
        ("నమస్కారం। మీరు ఎలా ఉన్నారు", "నమస్కారం।"),
        ("नमस्ते॥ आप कैसे हैं", "नमस्ते॥"),
        ("आपका ऑर्डर तैयार है। कल डिलीवरी", "आपका ऑर्डर तैयार है।"),
        ("మీ బుకింగ్ కన్ఫర్మ్ అయింది! రేపు కలుద్దాం", "మీ బుకింగ్ కన్ఫర్మ్ అయింది!"),
        ("Is 6 PM okay? I can call then", "Is 6 PM okay?"),
        ("Dr. Rao paid ₹1.5 lakh today. Next step", "Dr. Rao paid ₹1.5 lakh today."),
    ],
)
def test_first_sentence_ends_at_the_right_mark(text: str, first: str) -> None:
    for language in ("te", "hi", "en"):
        assert text[: match_endofsentence(text, language=language)] == first


def test_unfinished_text_is_not_a_sentence() -> None:
    assert match_endofsentence("మీరు ఎలా", language="te") == 0
    assert match_endofsentence("Dr", language="en") == 0


def test_streamed_llm_tokens_are_released_sentence_by_sentence() -> None:
    async def run() -> list[str]:
        aggregator = SimpleTextAggregator()
        out: list[str] = []
        for token in ["నమస్కారం", "। మీ", "రు ఎలా ", "ఉన్నారు?", " సరే"]:
            async for piece in aggregator.aggregate(token):
                out.append(piece.text)
        return out

    assert asyncio.run(run()) == ["నమస్కారం।", "మీరు ఎలా ఉన్నారు?"]
