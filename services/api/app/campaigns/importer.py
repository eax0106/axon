"""Read contacts from a CSV, a pasted list or a manual entry, and map columns to variables.

The mapping is never guessed: the caller names the column of the phone number, the column of the
name (or none), and for every variable the employee's script declares, the column that fills it (or
`null` to leave it empty on purpose). A column that does not exist, a variable the script does not
declare, or a declared variable nobody mentioned is an error that says so, before anything is saved.
"""

import csv
import io
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from app.actions.schema import IDENTIFIER
from app.employees.compiler import clean_value
from app.instant.intake import normalize_phone

MAX_ROWS = 20_000
MAX_TEXT = 5_000_000
NAME_LEN = 200
PASTE_SPLIT = re.compile(r"[\r\n,;]+")  # not spaces: 98765 43210 is one number


class MappingError(ValueError):
    """The upload cannot be read as asked; the message says what to change."""


class Mapping(BaseModel):
    phone: str = Field(min_length=1, max_length=200)
    name: str | None = Field(default=None, max_length=200)
    variables: dict[str, str | None] = Field(default_factory=dict, max_length=50)


@dataclass(frozen=True)
class Row:
    phone: str
    name: str | None = None
    variables: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Rejected:
    row: int  # 1 is the first row after the header
    value: str
    reason: str


@dataclass
class Parsed:
    rows: list[Row] = field(default_factory=list)
    invalid: list[Rejected] = field(default_factory=list)
    duplicates: int = 0  # the same number twice in the file: the first one is kept


def read_table(text: str) -> tuple[list[str], list[list[str]]]:
    """The header and the data rows of a comma-separated file."""
    if len(text) > MAX_TEXT:
        raise MappingError(f"the file is over {MAX_TEXT // 1_000_000} MB")
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    rows = [r for r in rows if any(cell.strip() for cell in r)]
    if not rows:
        raise MappingError("the file is empty")
    header = [h.strip() for h in rows[0]]
    if len(rows) - 1 > MAX_ROWS:
        raise MappingError(f"the file has more than {MAX_ROWS} rows; split it")
    return header, rows[1:]


def check_mapping(header: Sequence[str], mapping: Mapping, declared: Sequence[str] | None) -> None:
    """Raise MappingError unless every name in the mapping is a real column and, when `declared` is
    given, the mapping covers exactly the declared variables."""
    if len(set(header)) != len(header) or "" in header:
        raise MappingError("the header row has an empty or repeated column name")
    named = [mapping.phone, *([mapping.name] if mapping.name else [])]
    named += [c for c in mapping.variables.values() if c is not None]
    missing = [c for c in named if c not in header]
    if missing:
        raise MappingError(f"no column named {missing[0]!r}; the columns are {', '.join(header)}")
    bad = [v for v in mapping.variables if not IDENTIFIER.match(v)]
    if bad:
        raise MappingError(
            f"{bad[0]!r} is not a valid variable name (lowercase letters, digits, _)"
        )
    if declared is not None:
        unknown = [v for v in mapping.variables if v not in declared]
        if unknown:
            raise MappingError(f"the script does not declare a variable {unknown[0]!r}")
        unmapped = [v for v in declared if v not in mapping.variables]
        if unmapped:
            raise MappingError(
                f"say which column fills {unmapped[0]!r} (or null to leave it empty): "
                "columns are never matched by guesswork"
            )


def parse_csv(text: str, mapping: Mapping, declared: Sequence[str] | None) -> Parsed:
    header, body = read_table(text)
    check_mapping(header, mapping, declared)
    at = {name: i for i, name in enumerate(header)}
    out = Parsed()
    seen: set[str] = set()
    for number, cells in enumerate(body, start=1):

        def cell(column: str | None, cells: list[str] = cells) -> str:
            return cells[at[column]] if column and at[column] < len(cells) else ""

        raw = cell(mapping.phone)
        phone = normalize_phone(raw)
        if phone is None:
            out.invalid.append(Rejected(number, clean_value(raw), "not an Indian mobile number"))
            continue
        if phone in seen:
            out.duplicates += 1
            continue
        seen.add(phone)
        variables = {
            var: clean_value(cell(column))
            for var, column in mapping.variables.items()
            if column is not None and cell(column).strip()
        }
        name = clean_value(cell(mapping.name))[:NAME_LEN] if mapping.name else ""
        out.rows.append(Row(phone, name or None, variables))
    return out


def parse_paste(text: str) -> Parsed:
    """One number per line (commas and semicolons also separate them; a space does not, so
    `98765 43210` is one number): no names, no variables."""
    if len(text) > MAX_TEXT:
        raise MappingError(f"the text is over {MAX_TEXT // 1_000_000} MB")
    tokens = [t.strip() for t in PASTE_SPLIT.split(text) if t.strip()]
    if len(tokens) > MAX_ROWS:
        raise MappingError(f"more than {MAX_ROWS} numbers; split them")
    if not tokens:
        raise MappingError("no numbers were pasted")
    out = Parsed()
    seen: set[str] = set()
    for number, raw in enumerate(tokens, start=1):
        phone = normalize_phone(raw)
        if phone is None:
            out.invalid.append(Rejected(number, clean_value(raw), "not an Indian mobile number"))
        elif phone in seen:
            out.duplicates += 1
        else:
            seen.add(phone)
            out.rows.append(Row(phone))
    return out


def one(
    phone: str, name: str | None, variables: dict[str, str], declared: Sequence[str] | None
) -> Row:
    """One contact typed in by hand. Variables the script does not declare are an error."""
    clean = normalize_phone(phone)
    if clean is None:
        raise MappingError(f"{clean_value(phone)!r} is not an Indian mobile number")
    if declared is not None:
        unknown = [v for v in variables if v not in declared]
        if unknown:
            raise MappingError(f"the script does not declare a variable {unknown[0]!r}")
    return Row(
        clean,
        clean_value(name)[:NAME_LEN] or None if name else None,
        {k: clean_value(v) for k, v in variables.items() if str(v).strip()},
    )
