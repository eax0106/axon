"""Words the speech-to-text should hear right on a call: names, places, brands and products.

Built automatically from the employee and the lead, then passed as recognition hints (Sarvam
`keyterms`, Soniox context terms, ElevenLabs `keyterms`). Hints bias recognition; they do not
force a word into the transcript, and too many common words cause false hits, so only names are
taken: the lead's name, the business, the employee, short values from the lead's fields, and the
proper nouns of the script (capitalised words and acronyms written in English letters). Names
the owner or the lead source wrote in Telugu or Hindi script are passed as written.
ponytail: a Latin-only name is not also given in Telugu or Hindi script; that needs the owner's
text transliterated (Sarvam Transliterate) at publish time.
"""

import re
from collections.abc import Iterable

MAX_TERMS = 50  # Saaras v4 takes at most 50
MAX_CHARS = 64  # of up to 64 characters each
MAX_WORDS = 4
# A run of capitalised words (with an optional title such as "Dr."), or an acronym like BHK.
_PROPER = re.compile(r"\b(?:(?:Dr|Mr|Mrs|Ms|Sri|Smt)\.?\s+)?[A-Z][\w&'-]*(?:\s+[A-Z][\w&'-]*)*")
_SENTENCE_START = re.compile(r"(?:^|[.!?:;\n]\s*|[\"'(]\s*)$")
# Capitalised only because they open a sentence or are everyday words, not names.
_COMMON = {
    "a", "an", "and", "are", "ask", "be", "but", "can", "do", "for", "hello", "hi", "how", "i",
    "if", "in", "is", "it", "its", "no", "not", "ok", "okay", "on", "or", "our", "please",
    "say", "sir", "madam", "so", "tell", "thank", "thanks", "that", "the", "then", "this",
    "to", "we", "what", "when", "where", "which", "who", "why", "yes", "you", "your", "faq",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
}  # fmt: skip
_DIGITS_OR_CONTACT = re.compile(r"\d|@|https?://")


def _clean(term: str) -> str | None:
    term = " ".join(term.split()).strip(" .,;:!?\"'()-")
    if len(term) < 2 or len(term) > MAX_CHARS or len(term.split()) > MAX_WORDS:
        return None
    if _DIGITS_OR_CONTACT.search(term) or term.lower() in _COMMON:
        return None
    return term if any(c.isalpha() for c in term) else None


def proper_nouns(text: str) -> list[str]:
    """Capitalised names and acronyms in English letters. A single capitalised word that only
    opens a sentence is skipped: it is more often "Please" than a name."""
    found = []
    for match in _PROPER.finditer(text):
        phrase = match.group(0)
        words = phrase.split()
        opens = _SENTENCE_START.search(text[: match.start()]) is not None
        while words and words[0].lower() in _COMMON:  # "Our Skyline Habitats" -> the name
            words.pop(0)
            opens = False
        if not words or (len(words) == 1 and opens and not words[0].isupper()):
            continue
        found.append(" ".join(words))
    return found


def build(
    *,
    lead_name: str | None,
    business: str,
    employee: str,
    lead_values: Iterable[str] = (),
    script: Iterable[str] = (),
) -> tuple[str, ...]:
    """At most MAX_TERMS hints, de-duplicated: the lead, the business and the employee first,
    then the lead's other values and the script's names, longest first."""
    first = [lead_name or "", business, employee]
    rest = [*lead_values, *(name for text in script for name in proper_nouns(text))]
    terms: dict[str, str] = {}
    for term in [*first, *sorted(rest, key=len, reverse=True)]:
        cleaned = _clean(term)
        if cleaned is not None:
            terms.setdefault(cleaned.casefold(), cleaned)
    return tuple(terms.values())[:MAX_TERMS]
