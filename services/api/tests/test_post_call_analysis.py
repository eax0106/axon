"""Nothing invented: every claim the extractor keeps must be backed by the transcript."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.calls import analysis
from app.calls.analysis import Analysis, AnalysisError
from app.employees.script import CaptureField
from app.providers.base import ChatMessage, LLMProvider

NOW = datetime(2026, 11, 2, 8, 0, tzinfo=UTC)  # 13:30 IST on a Monday
CAPTURE = [
    CaptureField(name="budget", description="Monthly budget"),
    CaptureField(name="city", description="City the caller lives in"),
]
TURNS: list[dict[str, Any]] = [
    {"role": "assistant", "text": "Hello, this is Asha from SunBright Solar. Is this a good time?"},
    {"role": "user", "text": "Yes. I am in Hyderabad and my budget is around five lakh rupees."},
    {"role": "assistant", "text": "Great. Can I call you back with a quote?"},
    {"role": "user", "text": "Please call me tomorrow at 6 in the evening."},
]
TELUGU: list[dict[str, Any]] = [
    {"role": "assistant", "text": "నమస్కారం, నేను ఆశా."},
    {"role": "user", "text": "నేను హైదరాబాద్ లో ఉంటాను, నా బడ్జెట్ ఐదు లక్షలు."},
]


class Model(LLMProvider):
    """Stands in for the LLM vendor in these tests only: it returns a recorded reply."""

    name = "recorded"

    def __init__(self, reply: str) -> None:
        self.reply, self.asked = reply, 0
        self.system = ""
        self.prompt = ""

    async def health(self) -> None:
        return None

    async def complete(
        self, system: str, messages: list[ChatMessage], *, json_output: bool = False
    ) -> str:
        self.asked += 1
        self.system, self.prompt = system, messages[0]["content"]
        assert json_output
        return self.reply


def reply(**changes: Any) -> str:
    """A reply in the shape the prompt asks for, as a model would send it."""
    base: dict[str, Any] = {
        "summary": "Asha called about solar panels. The caller lives in Hyderabad.",
        "sentiment": "positive",
        "outcome": "callback_requested",
        "captured": {
            "budget": {
                "value": "five lakh rupees",
                "quote": "my budget is around five lakh rupees",
            },
            "city": {"value": "Hyderabad", "quote": "I am in Hyderabad"},
        },
        "callback": {
            "at": "2026-11-03T18:00:00+05:30",
            "quote": "call me tomorrow at 6 in the evening",
        },
        "do_not_call": {"requested": False, "quote": None},
        "memory": "Lives in Hyderabad, budget about five lakh.",
    }
    base.update(changes)
    return json.dumps(base)


def run(text: str, turns: list[dict[str, Any]] = TURNS, **kw: Any) -> Analysis:
    model = Model(text)
    return asyncio.run(analysis.analyse(model, turns, CAPTURE, NOW, **kw))


def test_a_well_supported_reply_is_kept_whole() -> None:
    result = run(reply())
    assert (
        result.summary and result.sentiment == "positive" and result.outcome == "callback_requested"
    )
    assert result.captured == {"budget": "five lakh rupees", "city": "Hyderabad"}
    assert result.callback_at == datetime(2026, 11, 3, 12, 30, tzinfo=UTC)
    assert not result.do_not_call and result.memory == "Lives in Hyderabad, budget about five lakh."


def test_a_value_whose_quote_is_not_in_the_transcript_is_null() -> None:
    captured = {
        "budget": {"value": "ten lakh", "quote": "my budget is ten lakh rupees"},  # never said
        "city": {"value": "Hyderabad", "quote": "I am in Hyderabad"},
    }
    result = run(reply(captured=captured))
    assert result.captured == {"budget": None, "city": "Hyderabad"}


def test_a_value_with_no_quote_or_no_value_is_null() -> None:
    captured = {"budget": {"value": "5 lakh", "quote": None}, "city": {"value": None, "quote": "x"}}
    assert run(reply(captured=captured)).captured == {"budget": None, "city": None}
    assert run(reply(captured="nonsense")).captured == {"budget": None, "city": None}
    assert run(reply(captured={"budget": "five lakh"})).captured == {"budget": None, "city": None}


def test_fields_nobody_declared_are_dropped_and_missing_ones_are_null() -> None:
    captured = {"income": {"value": "1 lakh", "quote": "my budget is around five lakh rupees"}}
    result = run(reply(captured=captured))
    assert result.captured == {"budget": None, "city": None}  # exactly the declared fields


def test_quotes_are_matched_ignoring_case_punctuation_and_spacing() -> None:
    captured = {
        "budget": {"value": "five lakh", "quote": "MY BUDGET is  around five lakh, rupees!"},
        "city": {"value": "Hyderabad", "quote": "i am in hyderabad."},
    }
    assert run(reply(captured=captured)).captured == {"budget": "five lakh", "city": "Hyderabad"}


def test_telugu_quotes_are_checked_too() -> None:
    wanted = [CaptureField(name="city", description="City")]
    good = {"city": {"value": "హైదరాబాద్", "quote": "నేను హైదరాబాద్ లో ఉంటాను"}}
    bad = {"city": {"value": "చెన్నై", "quote": "నేను చెన్నై లో ఉంటాను"}}
    for captured, expected in ((good, "హైదరాబాద్"), (bad, None)):
        model = Model(reply(captured=captured, callback={"at": None, "quote": None}))
        got = asyncio.run(analysis.analyse(model, TELUGU, wanted, NOW))
        assert got.captured == {"city": expected}


def test_outcomes_and_sentiments_outside_the_lists_are_null() -> None:
    result = run(reply(outcome="sold_it", sentiment="ecstatic"))
    assert result.outcome is None and result.sentiment is None
    assert run(reply(outcome=None, sentiment=None)).outcome is None
    assert run(reply(outcome=["interested"], sentiment=3)).sentiment is None


def test_the_summary_is_trimmed_and_empty_means_null() -> None:
    assert run(reply(summary="  ")).summary is None
    assert run(reply(summary=None)).summary is None
    assert run(reply(summary=12)).summary is None
    assert len(run(reply(summary="x " * 800)).summary or "") <= analysis.MAX_SUMMARY


@pytest.mark.parametrize(
    "bad", ["", "no json at all", "[1, 2]", "{broken", "```json\nnot json\n```"]
)
def test_unusable_output_is_a_failed_analysis_never_a_guess(bad: str) -> None:
    with pytest.raises(AnalysisError):
        run(bad)


def test_a_fenced_reply_is_fine() -> None:
    assert run(f"```json\n{reply()}\n```").outcome == "callback_requested"


def test_a_callback_needs_a_future_time_within_two_weeks_and_the_callers_own_words() -> None:
    quote = "call me tomorrow at 6 in the evening"

    def at(value: Any, said: str = quote) -> datetime | None:
        return run(reply(callback={"at": value, "quote": said})).callback_at

    assert at("2026-11-03T18:00:00+05:30") is not None
    assert at("2026-11-03T18:00:00") == datetime(2026, 11, 3, 12, 30, tzinfo=UTC)  # naive = IST
    assert at("2026-11-02T10:00:00+05:30") is None  # already past (13:30 IST now)
    assert at((NOW + timedelta(days=15)).isoformat()) is None
    assert at((NOW + timedelta(days=13)).isoformat()) is not None
    assert at("tomorrow evening") is None and at(None) is None and at(7) is None
    assert at("2026-11-03T18:00:00+05:30", "call me on Sunday") is None  # quote not in the call
    agent_only = "Can I call you back with a quote"  # the agent said it, not the caller
    assert at("2026-11-03T18:00:00+05:30", agent_only) is None


def test_do_not_call_needs_the_callers_own_words_and_sets_the_outcome() -> None:
    turns = [
        *TURNS,
        {"role": "user", "text": "Actually, please stop calling me. Do not call again."},
    ]
    said = {"requested": True, "quote": "please stop calling me"}
    result = run(reply(do_not_call=said, outcome="not_interested"), turns)
    assert result.do_not_call and result.outcome == "do_not_call"
    invented = {"requested": True, "quote": "please never ring this number"}
    result = run(reply(do_not_call=invented, outcome="do_not_call"), turns)
    assert (
        not result.do_not_call and result.outcome is None
    )  # the model's claim alone is not enough
    by_agent = {"requested": True, "quote": "Is this a good time"}
    assert not run(reply(do_not_call=by_agent), turns).do_not_call
    assert not run(
        reply(do_not_call={"requested": "yes", "quote": "stop calling me"}), turns
    ).do_not_call


def test_memory_is_only_kept_when_the_account_remembers_callers() -> None:
    assert run(reply(), remember=False).memory is None
    assert run(reply(memory="  likes calls after lunch  ")).memory == "likes calls after lunch"
    assert len(run(reply(memory="y " * 900)).memory or "") <= analysis.MAX_MEMORY


def test_a_call_with_no_caller_speech_is_not_sent_to_the_model() -> None:
    model = Model(reply())
    for turns in (
        [],
        [{"role": "assistant", "text": "Hello? Hello?"}],
        [{"role": "user", "text": " "}],
    ):
        got = asyncio.run(analysis.analyse(model, turns, CAPTURE, NOW))
        assert got.outcome == "no_conversation" and got.summary is None
        assert got.captured == {"budget": None, "city": None}
    assert model.asked == 0


def test_the_prompt_carries_the_transcript_the_fields_and_the_clock() -> None:
    model = Model(reply())
    asyncio.run(analysis.analyse(model, TURNS, CAPTURE, NOW, old_memory="Prefers evenings."))
    assert (
        "Caller: Yes. I am in Hyderabad" in model.prompt
        and "Agent: Hello, this is Asha" in model.prompt
    )
    assert "- budget: Monthly budget" in model.prompt and "Prefers evenings." in model.prompt
    assert "Monday 02 November 2026, 13:30" in model.prompt
    assert "Never guess" in model.system and "word for word" in model.system
    off = Model(reply())
    asyncio.run(analysis.analyse(off, TURNS, CAPTURE, NOW, old_memory="secret", remember=False))
    assert "secret" not in off.prompt and "memory is off" in off.prompt


def captured_with(
    value: str, quote: str, turns: list[dict[str, Any]] = TURNS
) -> dict[str, str | None]:
    entry = {"budget": {"value": value, "quote": quote}, "city": {"value": None, "quote": None}}
    return run(reply(captured=entry), turns).captured


@pytest.mark.parametrize("trivial", ["ok", "no", "yes", "ha", "Yes.", "I", "  "])
def test_a_trivial_quote_proves_nothing(trivial: str) -> None:
    turns = [*TURNS, {"role": "user", "text": "Yes. Okay, no problem. Ha."}]
    assert captured_with("yes", trivial, turns)["budget"] is None
    callback = {"at": "2026-11-03T18:00:00+05:30", "quote": trivial}
    assert run(reply(callback=callback), turns).callback_at is None


def test_a_lone_no_cannot_put_a_number_on_the_do_not_call_list() -> None:
    turns = [{"role": "assistant", "text": "Shall I call again?"}, {"role": "user", "text": "No."}]
    for quote in ("no", "No.", "No"):
        result = run(
            reply(do_not_call={"requested": True, "quote": quote}, outcome="do_not_call"), turns
        )
        assert not result.do_not_call and result.outcome is None


def test_short_but_real_quotes_are_accepted() -> None:
    assert (
        captured_with("500081", "500081", [{"role": "user", "text": "My pincode is 500081."}])[
            "budget"
        ]
        == "500081"
    )
    two_words = [{"role": "user", "text": "Please stop calling."}]
    assert run(
        reply(do_not_call={"requested": True, "quote": "stop calling"}), two_words
    ).do_not_call


def test_words_the_agent_said_are_never_a_quote() -> None:
    agent_line = "Is this a good time"
    assert captured_with("a good time", agent_line)["budget"] is None
    label = "Caller Yes I am in Hyderabad"  # the transcript labels are not speech
    assert captured_with("Hyderabad", label)["budget"] is None


def test_a_quote_cannot_be_stitched_together_from_two_caller_turns() -> None:
    turns = [
        {"role": "user", "text": "I live in Hyderabad."},
        {"role": "assistant", "text": "Great."},
        {"role": "user", "text": "My budget is five lakh."},
    ]
    stitched = "Hyderabad My budget is five lakh"
    assert captured_with("five lakh", stitched, turns)["budget"] is None
    assert captured_with("five lakh", "My budget is five lakh", turns)["budget"] == "five lakh"
    callback = {"at": "2026-11-03T18:00:00+05:30", "quote": "Hyderabad My budget"}
    assert run(reply(callback=callback), turns).callback_at is None
    stop = {"requested": True, "quote": "Hyderabad My budget"}
    assert not run(reply(do_not_call=stop), turns).do_not_call


def test_the_value_must_be_made_of_the_words_of_its_quote() -> None:
    quote = "my budget is around five lakh rupees"
    assert captured_with("five lakh rupees", quote)["budget"] == "five lakh rupees"
    assert captured_with("Five Lakh", quote)["budget"] == "Five Lakh"  # case is not a rewrite
    assert captured_with("ten lakh", quote)["budget"] is None  # a different number
    assert captured_with("5 lakh", quote)["budget"] is None  # converted, not said
    assert captured_with("₹10 lakh", "yes my budget is around five lakh rupees")["budget"] is None
    assert captured_with("", quote)["budget"] is None


HINDI: list[dict[str, Any]] = [
    {"role": "assistant", "text": "नमस्ते, मैं आशा बोल रही हूँ। क्या मैं आपसे बात कर सकती हूँ?"},
    {"role": "user", "text": "मेरा बजट पांच लाख रुपये है। मुझे फोन मत करो, धन्यवाद।"},
]
TELUGU_CALL: list[dict[str, Any]] = [
    {"role": "assistant", "text": "నమస్కారం, నేను ఆశా మాట్లాడుతున్నాను."},
    {"role": "user", "text": "నేను హైదరాబాద్ లో ఉంటాను. ఇంకా నాకు ఫోన్ చేయవద్దు, ధన్యవాదాలు."},
]


def test_normalising_keeps_indian_language_words_whole() -> None:
    """Vowel signs and the virama are combining marks, not punctuation: they stay in their word."""
    assert analysis._norm("मुझे फोन मत करो, धन्यवाद।") == "मुझे फोन मत करो धन्यवाद"
    assert analysis._norm("వద్దు!") == "వద్దు"
    assert analysis._norm("హైదరాబాద్ లో ఉంటాను.") == "హైదరాబాద్ లో ఉంటాను"
    assert analysis._norm("  Hello,  WORLD!! ₹5 ") == "hello world 5"  # symbols and punctuation go
    assert analysis._norm("a_b-c") == "a b c"


def test_a_real_hindi_quote_is_accepted_and_a_shredded_one_is_not() -> None:
    assert analysis.caller_quoted("मुझे फोन मत करो", HINDI) == "मुझे फोन मत करो"
    assert analysis.caller_quoted("मुझे फोन मत करो।", HINDI) == "मुझे फोन मत करो"
    for shredded in ("म झ फ न मत कर", "म झ फ न", "मझ फन मत कर", "ुझे ोन"):
        assert analysis.caller_quoted(shredded, HINDI) is None, shredded
    stop = {"requested": True, "quote": "मुझे फोन मत करो"}
    result = run(reply(do_not_call=stop), HINDI)
    assert result.do_not_call and result.do_not_call_quote == "मुझे फोन मत करो"
    assert not run(
        reply(do_not_call={"requested": True, "quote": "म झ फ न मत कर"}), HINDI
    ).do_not_call


def test_a_real_telugu_quote_is_accepted_and_a_shredded_one_is_not() -> None:
    assert analysis.caller_quoted("నాకు ఫోన్ చేయవద్దు", TELUGU_CALL) == "నాకు ఫోన్ చేయవద్దు"
    for shredded in ("న క ఫ న చ య వ ద ద", "వద ద", "హ దర బ ద"):
        assert analysis.caller_quoted(shredded, TELUGU_CALL) is None, shredded
    stop = {"requested": True, "quote": "నాకు ఫోన్ చేయవద్దు"}
    assert run(reply(do_not_call=stop), TELUGU_CALL).do_not_call
    assert not run(
        reply(do_not_call={"requested": True, "quote": "న క ఫ న చ య"}), TELUGU_CALL
    ).do_not_call


def test_a_captured_value_in_devanagari_or_telugu_must_be_the_words_of_its_quote() -> None:
    quote = analysis._norm("मेरा बजट पांच लाख रुपये है")
    assert analysis.value_in_quote("पांच लाख", quote)
    assert analysis.value_in_quote("पांच लाख रुपये", quote)
    assert not analysis.value_in_quote("दस लाख", quote)  # a different number
    assert not analysis.value_in_quote("5 लाख", quote)  # converted, not said
    assert not analysis.value_in_quote("प च ल ख", quote)  # consonants only
    assert not analysis.value_in_quote("ां", quote)  # a lone mark
    telugu = analysis._norm("నేను హైదరాబాద్ లో ఉంటాను")
    assert analysis.value_in_quote("హైదరాబాద్", telugu)
    assert not analysis.value_in_quote("చెన్నై", telugu)
    assert not analysis.value_in_quote("ద్", telugu) and not analysis.value_in_quote("హ దర", telugu)


def test_captured_values_in_hindi_and_telugu_end_to_end() -> None:
    wanted = [
        CaptureField(name="budget", description="बजट"),
        CaptureField(name="city", description="शहर"),
    ]
    given = {
        "budget": {"value": "पांच लाख", "quote": "मेरा बजट पांच लाख रुपये है"},
        "city": {"value": "दिल्ली", "quote": "मेरा बजट पांच लाख रुपये है"},  # not in the quote
    }
    model = Model(reply(captured=given, callback={"at": None, "quote": None}))
    got = asyncio.run(analysis.analyse(model, HINDI, wanted, NOW))
    assert got.captured == {"budget": "पांच लाख", "city": None}
