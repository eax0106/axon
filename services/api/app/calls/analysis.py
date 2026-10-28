"""What a finished call tells us: summary, sentiment, outcome, captured fields, a requested
callback and a do-not-call request, taken from the transcript by the LLM, and checked.

Nothing is invented. The model must quote the words that support every captured value, a
callback time and a do-not-call request; a quote that is not in the transcript (or, for the
last two, not something the caller said) makes the value null. Outcomes and sentiments outside
the allowed lists become null. Output that is not the expected JSON is a failed analysis, never
a guessed one, and a call where the caller said nothing is not sent to the model at all.
"""

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
MAX_STRUGGLES, MAX_QUOTE, MAX_RULE = 3, 200, 300

Turns = list[dict[str, Any]]  # [{"role": "user" | "assistant", "text": "..."}]


class AnalysisError(Exception):
    """The model's answer could not be used; the call's analysis is marked failed."""


@dataclass(frozen=True)
class Struggle:
    """A moment on the call where the employee fell short, with the words that show it.
    `text` is what to teach: empty for a gap, because only the owner knows the answer."""

    kind: str  # fact (a gap in what it knows) or rule (something it did that it should not)
    reason: str  # unanswered or conduct
    caller_quote: str
    agent_quote: str | None
    text: str


@dataclass
class Analysis:
    summary: str | None = None
    sentiment: str | None = None
    outcome: str | None = None
    captured: dict[str, str | None] = field(default_factory=dict)
    callback_at: datetime | None = None
    do_not_call: bool = False
    do_not_call_quote: str | None = None  # the caller's words, so the owner can see why
    message: str | None = None  # what the caller asked us to pass on, if they said so
    memory: str | None = None
    voicemail: bool = False  # the Caller side was a recorded greeting, quoted from the transcript
    struggles: list[Struggle] = field(default_factory=list)


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
    folded = unicodedata.normalize("NFKC", text).casefold()
    # Only punctuation (P*) and symbols (S*) become spaces. Combining marks (M*: the vowel signs
    # and virama of Hindi and Telugu) belong to their word: dropping them would shred a word into
    # its consonants.
    spaced = "".join(" " if unicodedata.category(c)[0] in "PS" else c for c in folded)
    return " ".join(spaced.split())


MIN_QUOTE_CHARS = 6  # "yes", "no" and "ok" are in almost every call and prove nothing
MIN_QUOTE_WORDS = 2


def _long_enough(quote: str) -> bool:
    return len(quote) >= MIN_QUOTE_CHARS or len(quote.split()) >= MIN_QUOTE_WORDS


def _quoted(quote: object, turns: Turns, role: str) -> str | None:
    if not isinstance(quote, str):
        return None
    wanted = _norm(quote)
    if not wanted or not _long_enough(wanted):
        return None
    for turn in turns:
        if turn.get("role") == role and wanted in _norm(str(turn.get("text", ""))):
            return wanted
    return None


def caller_quoted(quote: object, turns: Turns) -> str | None:
    """The normalised quote, if it is a real quote: long enough and inside ONE turn the caller
    spoke. Agent lines, labels, and words spread over several turns do not count."""
    return _quoted(quote, turns, "user")


def agent_quoted(quote: object, turns: Turns) -> str | None:
    """The same for the employee's own words: inside ONE turn the Agent spoke."""
    return _quoted(quote, turns, "assistant")


def value_in_quote(value: str, quote: str) -> bool:
    """Every word of the value is a word of the quote: the value is what the caller said, not a
    rewrite of it."""
    words = set(quote.split())
    tokens = _norm(value).split()
    return bool(tokens) and all(token in words for token in tokens)


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
    ' "message": {"text": "what the Caller asked to pass on to the business, in one or two plain'
    ' sentences, or null", "quote": "their exact words, or null"},'
    ' "do_not_call": {"requested": true or false, "quote": "their exact words, or null"},'
    ' "voicemail": {"detected": true or false, "quote": "the exact words of the recording, or'
    ' null"},'
    ' "memory": "at most three short sentences of lasting facts about this person worth '
    'remembering for the next call, or null",'
    ' "struggles": [{"reason": "unanswered | conduct", "caller_quote": "the exact words of the'
    ' Caller", "agent_quote": "the exact words of the Agent, or null", "rule": "for conduct only:'
    ' one short rule that would have avoided it, or null"}]}\n'
    "Voicemail means the Caller side was a recorded greeting or an answering machine (for example"
    " asking to leave a message after a tone), not a person talking to the Agent; quote the"
    " recording's words.\n"
    "A struggle is a moment where the Agent could not or would not answer a question the Caller"
    " asked (unanswered), or did something the business would not want, such as promising what"
    " was never offered, ignoring a request or pressing after a no (conduct). List at most 3 and"
    " leave the list empty if there were none. For conduct quote the Agent's own words too.\n"
    "A quote must be copied word for word from ONE thing the Caller said, never from the Agent. "
    "A captured value must use only words that are in its quote: copy the caller's own words, do "
    "not convert or rewrite them. Only the Caller can ask for a callback or ask not to be called "
    "again."
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
    result = Analysis(
        summary=_clean(data.get("summary"), MAX_SUMMARY),
        sentiment=data.get("sentiment") if data.get("sentiment") in SENTIMENTS else None,
        outcome=data.get("outcome") if data.get("outcome") in OUTCOMES else None,
    )
    given = _entry(data.get("captured"))
    for wanted in capture:  # only declared fields; a field the model skipped is simply null
        entry = _entry(given.get(wanted.name))
        value = _clean(entry.get("value"), MAX_VALUE)
        quote = caller_quoted(entry.get("quote"), turns)
        keep = value is not None and quote is not None and value_in_quote(value, quote)
        result.captured[wanted.name] = value if keep else None
    callback = _entry(data.get("callback"))
    when = _future_time(callback.get("at"), now)
    if when and caller_quoted(callback.get("quote"), turns):
        result.callback_at = when
    said = _entry(data.get("message"))
    if caller_quoted(said.get("quote"), turns):  # a message nobody left is not written for them
        result.message = _clean(said.get("text"), MAX_VALUE)
    dnc = _entry(data.get("do_not_call"))
    result.do_not_call = (
        dnc.get("requested") is True and caller_quoted(dnc.get("quote"), turns) is not None
    )
    if result.do_not_call:
        result.do_not_call_quote = _clean(dnc.get("quote"), 200)
    recorded = _entry(data.get("voicemail"))
    result.voicemail = (
        recorded.get("detected") is True and caller_quoted(recorded.get("quote"), turns) is not None
    )
    if result.outcome == "do_not_call" and not result.do_not_call:
        result.outcome = None  # the model said so but nothing the caller said backs it
    if result.do_not_call:
        result.outcome = "do_not_call"
    if remember:
        result.memory = _clean(data.get("memory"), MAX_MEMORY)
    result.struggles = _struggles(data.get("struggles"), turns)
    return result


def _struggles(raw: object, turns: Turns) -> list[Struggle]:
    """Only what the transcript shows: the caller's words must be real, and a rule needs the
    Agent's real words too. A gap carries no text, since only the owner knows the answer."""
    found: list[Struggle] = []
    for item in raw if isinstance(raw, list) else []:
        entry = _entry(item)
        caller = _clean(entry.get("caller_quote"), MAX_QUOTE)
        if not caller or not caller_quoted(caller, turns):
            continue
        said = _clean(entry.get("agent_quote"), MAX_QUOTE)
        agent = said if said and agent_quoted(said, turns) else None
        rule = _clean(entry.get("rule"), MAX_RULE)
        if entry.get("reason") == "unanswered":
            found.append(Struggle("fact", "unanswered", caller, agent, ""))
        elif entry.get("reason") == "conduct" and agent and rule:
            found.append(Struggle("rule", "conduct", caller, agent, rule))
        if len(found) == MAX_STRUGGLES:
            break
    return found


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
