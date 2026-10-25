"""The hook where the purpose x number-type rule table plugs in (B7).

DECISIONS: every employee declares a purpose (promotional / service / transactional), numbers have
a type (regular / 140 / 1600), and a configurable table allows or blocks each pairing before a
dial, with the Instant strict-or-relaxed setting pending the legal opinion. The table does not
exist yet, so today every dial is allowed. Every place that places a call asks `check_dial`
first, so B7 only has to replace this one function.
"""

from dataclasses import dataclass

from app.models import Employee, PhoneNumber


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason: str = ""


def check_dial(employee: Employee, number: PhoneNumber, to_phone: str) -> Verdict:
    # ponytail: no rule table until B7; allow everything rather than invent legal rules.
    return Verdict(True)
