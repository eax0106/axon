"""What a finished call tells us: summary, sentiment, outcome, captured fields, a requested
callback and a do-not-call request, taken from the transcript by the LLM, and checked.

Nothing is invented. The model must quote the words that support every captured value, a
callback time and a do-not-call request; a quote that is not in the transcript (or, for the
last two, not something the caller said) makes the value null. Outcomes and sentiments outside
the allowed lists become null. Output that is not the expected JSON is a failed analysis, never
a guessed one, and a call where the caller said nothing is not sent to the model at all.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from app.employees.ai import AiOutputError, parse_json
from app.employees.script import CaptureField
from app.providers.base import LLMProvider

OUTCOMES = (
    "interested",
    "not_interested",
    "callback_requested",
    "wrong_number",
    "do_not_call",
    "no_conversation",
    "other",
)
SENTIMENTS = ("positive", "neutral", "negative")
IST = timezone(timedelta(minutes=330))
MIN_CALLER_CHARS = 3  # less than this of caller speech is not a conversation
MAX_CALLBACK_AHEAD = timedelta(days=14)
MAX_SUMMARY, MAX_MEMORY, MAX_VALUE = 600, 600, 300

Turns = list[dict[str, Any]]  # [{"role": "user" | "assistant", "text": "..."}]


class AnalysisError(Exception):
    """The model's answer could not be used; the call's analysis is marked failed."""


@dataclass
class Analysis:
    summary: str | None = None
    sentiment: str | None = None
    outcome: str | None = None
    captured: dict[str, str | None] = field(default_factory=dict)
    callback_at: datetime | None = None
    do_not_call: bool = False
    memory: str | None = None


def caller_text(turns: Turns) -> str:
    return " ".join(str(t.get("text", "")) for t in turns if t.get("role") == "user")


def has_caller_speech(turns: Turns) -> bool:
    return len(caller_text(turns).strip()) >= MIN_CALLER_CHARS


def transcript_text(turns: Turns) -> str:
    names = {"user": "Caller", "assistant": "Agent"}
    return "\n".join(
        f"{names.get(str(t.get('role')), 'Agent')}: {t.get('text', '')}" for t in turns
    )


def _norm(text: str) -> str:
    """Case, accents, punctuation and spacing do not matter when checking a quote."""
    decomposed = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(re.sub(r"[^\w\s]", " ", decomposed).split())


def quoted(quote: object, haystack: str) -> bool:
    return isinstance(quote, str) and len(_norm(quote)) >= 2 and _norm(quote) in _norm(haystack)


SYSTEM = (
    "You review the transcript of one phone call between an AI phone employee (Agent) and a "
    "person (Caller) and report only what the transcript supports. Never guess. If something "
    "was not said, answer null. Reply with one JSON object only, nothing around it, "
    "in this shape:\n"
    '{"summary": "two or three plain sentences about what happened, or null",'
    ' "sentiment": "positive | neutral | negative | null",'
    ' "outcome": "one of: OUTCOME_LIST, or null",'
    ' "captured": {"<field name>": {"value": "what the caller said, or null",'
    ' "quote": "the exact words from the transcript that show it, or null"}},'
    ' "callback": {"at": "ISO 8601 date and time with offset when the caller asked to be called'
    ' back, or null", "quote": "their exact words, or null"},'
    ' "do_not_call": {"requested": true or false, "quote": "their exact words, or null"},'
    ' "memory": "at most three short sentences of lasting facts about this person worth '
    'remembering for the next call, or null"}\n'
    "A quote must be copied word for word from the transcript. Only the Caller can ask for a "
    "callback or ask not to be called again."
).replace("OUTCOME_LIST", ", ".join(OUTCOMES))


def build_user_prompt(
    turns: Turns, capture: list[CaptureField], now: datetime, old_memory: str | None, remember: bool
) -> str:
    wanted = "\n".join(f"- {c.name}: {c.description}" for c in capture) or "(none)"
    local = now.astimezone(IST).strftime("%A %d %B %Y, %H:%M")
    memory = (old_memory or "nothing yet") if remember else "(memory is off: answer null)"
    return (
        f"Now (India time, UTC+05:30): {local}. Work out a callback time from this.\n\n"
        f"Fields to capture:\n{wanted}\n\nWhat we remembered before this call: {memory}\n\n"
        f"Transcript:\n{transcript_text(turns)}"
    )


def _entry(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clean(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())[:limit]
    return text or None


def parse(
    reply: str,
    turns: Turns,
    capture: list[CaptureField],
    now: datetime,
    *,
    remember: bool,
) -> Analysis:
    try:
        data = parse_json(reply)
    except AiOutputError as exc:
        raise AnalysisError(str(exc.detail)) from exc
    everything, caller = transcript_text(turns), caller_text(turns)
    result = Analysis(
        summary=_clean(data.get("summary"), MAX_SUMMARY),
        sentiment=data.get("sentiment") if data.get("sentiment") in SENTIMENTS else None,
        outcome=data.get("outcome") if data.get("outcome") in OUTCOMES else None,
    )
    given = _entry(data.get("captured"))
    for wanted in capture:  # only declared fields; a field the model skipped is simply null
        entry = _entry(given.get(wanted.name))
        value = _clean(entry.get("value"), MAX_VALUE)
        result.captured[wanted.name] = (
            value if value and quoted(entry.get("quote"), everything) else None
        )
    callback = _entry(data.get("callback"))
    when = _future_time(callback.get("at"), now)
    if when and quoted(callback.get("quote"), caller):
        result.callback_at = when
    dnc = _entry(data.get("do_not_call"))
    result.do_not_call = dnc.get("requested") is True and quoted(dnc.get("quote"), caller)
    if result.outcome == "do_not_call" and not result.do_not_call:
        result.outcome = None  # the model said so but nothing the caller said backs it
    if result.do_not_call:
        result.outcome = "do_not_call"
    if remember:
        result.memory = _clean(data.get("memory"), MAX_MEMORY)
    return result


def _future_time(raw: object, now: datetime) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        at = datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    if at.tzinfo is None:
        at = at.replace(tzinfo=IST)
    at = at.astimezone(UTC)
    return at if now < at <= now + MAX_CALLBACK_AHEAD else None


async def analyse(
    llm: LLMProvider,
    turns: Turns,
    capture: list[CaptureField],
    now: datetime,
    *,
    old_memory: str | None = None,
    remember: bool = True,
) -> Analysis:
    """The analysis of one call. A call with no caller speech is a `no_conversation` and the model
    is not asked."""
    if not has_caller_speech(turns):
        return Analysis(outcome="no_conversation", captured=dict.fromkeys(c.name for c in capture))
    prompt = build_user_prompt(turns, capture, now, old_memory, remember)
    reply = await llm.complete(SYSTEM, [{"role": "user", "content": prompt}], json_output=True)
    return parse(reply, turns, capture, now, remember=remember)
