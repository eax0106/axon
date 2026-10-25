"""CSV that spreadsheets cannot be tricked by: a cell that starts with =, +, - or @ is read by
Excel and Sheets as a formula, and call data (names, transcripts, lead fields) is written by
strangers. Such cells get a leading apostrophe."""

import csv
import io
from collections.abc import Iterable, Sequence
from typing import Any

RISKY = ("=", "+", "-", "@", "\t", "\r")


def cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.lstrip().startswith(RISKY) else text


def to_csv(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow([cell(h) for h in header])
    for row in rows:
        writer.writerow([cell(v) for v in row])
    return out.getvalue()
