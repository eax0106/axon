"""The owner's "say it like this" list: respell words in what the voice is given, and only there.

It is a Pipecat text transform on every TTS vendor of the call, so it survives a failover and
needs no vendor dictionary. A reply chunk uses the list of the language it is written in (any
Telugu letter: Telugu, any Devanagari letter: Hindi, else English), so an English brand name
inside a Telugu sentence takes its Telugu respelling.

Vendors that report the words they spoke (Cartesia) hand the respelling back as the bot's text,
so the call transcript maps it back to the owner's word (`restore`).
"""

import re
from collections.abc import Iterable

# Indic vowel signs and the zero-width joiners inside words are not \w: keep words whole.
_LETTER = "\\w\u0900-\u097f\u0c00-\u0c7f\u200c\u200d"


def _language(text: str) -> str:
    if any("\u0c00" <= c <= "\u0c7f" for c in text):
        return "te"
    if any("\u0900" <= c <= "\u097f" for c in text):
        return "hi"
    return "en"


def _pattern(words: Iterable[str]) -> re.Pattern[str] | None:
    longest_first = sorted({w for w in words if w}, key=len, reverse=True)
    if not longest_first:
        return None
    alternatives = "|".join(re.escape(w) for w in longest_first)
    return re.compile(rf"(?<![{_LETTER}])(?:{alternatives})(?![{_LETTER}])", re.IGNORECASE)


class Pronouncer:
    def __init__(self, entries: Iterable[tuple[str, str, str]]) -> None:
        self._say: dict[str, dict[str, str]] = {}  # language -> word (casefolded) -> respelling
        self._word: dict[str, str] = {}  # respelling (casefolded) -> the owner's word
        for language, word, say in entries:
            self._say.setdefault(language, {})[word.casefold()] = say
            self._word[say.casefold()] = word
        self._forward = {lang: _pattern(words) for lang, words in self._say.items()}
        self._back = _pattern(self._word)

    def __bool__(self) -> bool:
        return bool(self._word)

    def speak(self, text: str) -> str:
        """The text as the voice should read it."""
        language = _language(text)
        pattern = self._forward.get(language)
        if pattern is None:
            return text
        table = self._say[language]
        return pattern.sub(lambda m: table[m.group(0).casefold()], text)

    def restore(self, text: str) -> str:
        """The bot's text with each respelling turned back into the owner's word."""
        if self._back is None:
            return text
        return self._back.sub(lambda m: self._word[m.group(0).casefold()], text)

    async def transform(self, text: str, _type: str) -> str:
        """Pipecat's TextTransform signature."""
        return self.speak(text)
