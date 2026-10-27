"""Cut a document into passages a search can return whole.

A passage ends at a sentence (a full stop, `?`, `!` or the Indic danda `।` `॥`) or a line, stays
within MAX_CHARS, and starts with the last sentence of the one before it so an answer that falls
on a boundary is still found in one piece.
"""

import re

MAX_CHARS = 700
OVERLAP_CHARS = 150  # the sentence carried into the next passage is at most this long
_BREAK = re.compile(r"(?<=[.!?।॥])\s+|\n+")


def _pieces(text: str) -> list[str]:
    pieces: list[str] = []
    for raw in _BREAK.split(text):
        sentence = " ".join(raw.split())
        while len(sentence) > MAX_CHARS:  # no break to use: cut at the last space, else mid-word
            cut = sentence.rfind(" ", 0, MAX_CHARS)
            cut = cut if cut > MAX_CHARS // 2 else MAX_CHARS
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if sentence:
            pieces.append(sentence)
    return pieces


def chunk(text: str) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    for piece in _pieces(text):
        if current and len(" ".join([*current, piece])) > MAX_CHARS:
            chunks.append(" ".join(current))
            last = current[-1]
            keep = len(last) <= OVERLAP_CHARS and len(f"{last} {piece}") <= MAX_CHARS
            current = [last] if keep else []
        current.append(piece)
    if current:
        chunks.append(" ".join(current))
    return chunks
