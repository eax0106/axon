"""May this employee dial from this number? The purpose x number-type rule table (DECISIONS).

Every employee declares a purpose (promotional / service / transactional), every number has a type
(regular / 140 / 1600), and a table of rows says yes or no for each pairing in each context:

  outbound   calling someone who has not just asked to be called
  callback   calling someone back at their own request
  inbound    answering a call
  instant    a lead who has just enquired; read under the platform's Instant setting

The Instant setting is `strict` (an Instant call counts as `outbound`) or `relaxed` (it uses the
`instant` rows). It is `strict` until the legal opinion says otherwise. A pairing with no row is
refused: the table fails closed. The default rows are seeded by migration 0005 and an admin can
change any of them.
"""

from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin
from app.db import Session
from app.models import DialRule, Employee, NumberType, PhoneNumber, PlatformSetting, Purpose

CONTEXTS = ("outbound", "callback", "inbound", "instant")
Context = Literal["outbound", "callback", "inbound", "instant"]
INSTANT_SETTING = "instant_policy"
STRICT, RELAXED = "strict", "relaxed"

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason: str = ""


async def instant_mode(session: AsyncSession) -> str:
    setting = await session.get(PlatformSetting, INSTANT_SETTING)
    return setting.value if setting and setting.value in (STRICT, RELAXED) else STRICT


async def check_dial(
    session: AsyncSession,
    employee: Employee,
    number: PhoneNumber,
    context: Context = "outbound",
    purpose: Purpose | None = None,
) -> Verdict:
    """The verdict for one dial. The reason is written for the person who sees why a call was
    cancelled. `purpose` overrides the employee's own (a campaign can declare another)."""
    purpose = purpose or employee.purpose
    if context == "instant" and await instant_mode(session) == STRICT:
        context = "outbound"
    rule = await session.scalar(
        select(DialRule).where(
            DialRule.purpose == purpose.value,
            DialRule.number_type == number.number_type.value,
            DialRule.context == context,
        )
    )
    if rule is None:
        return Verdict(
            False,
            f"no rule allows {purpose.value} calls from a {number.number_type.value} "
            f"number ({context}); an admin has to add one",
        )
    if rule.allowed:
        return Verdict(True)
    return Verdict(False, rule.reason or "the rule table does not allow this pairing")


class RuleBody(BaseModel):
    purpose: Purpose
    number_type: NumberType
    context: Context
    allowed: bool
    reason: str | None = None


@router.get("/dial-rules")
async def list_rules(session: Session) -> dict[str, object]:
    rows = await session.scalars(
        select(DialRule).order_by(DialRule.context, DialRule.purpose, DialRule.number_type)
    )
    return {
        "instant_policy": await instant_mode(session),
        "rules": [
            {
                "purpose": r.purpose,
                "number_type": r.number_type,
                "context": r.context,
                "allowed": r.allowed,
                "reason": r.reason,
            }
            for r in rows
        ],
    }


@router.put("/dial-rules")
async def set_rule(body: RuleBody, session: Session) -> RuleBody:
    values = {
        "purpose": body.purpose.value,
        "number_type": body.number_type.value,
        "context": body.context,
        "allowed": body.allowed,
        "reason": body.reason,
    }
    await session.execute(
        insert(DialRule)
        .values(values)
        .on_conflict_do_update(
            index_elements=["purpose", "number_type", "context"],
            set_={"allowed": body.allowed, "reason": body.reason},
        )
    )
    await session.commit()
    return body


class InstantBody(BaseModel):
    mode: Literal["strict", "relaxed"]  # strict reads an Instant call as outbound


@router.put("/instant-policy")
async def set_instant_policy(body: InstantBody, session: Session) -> InstantBody:
    await session.execute(
        insert(PlatformSetting)
        .values(key=INSTANT_SETTING, value=body.mode)
        .on_conflict_do_update(index_elements=["key"], set_={"value": body.mode})
    )
    await session.commit()
    return body
