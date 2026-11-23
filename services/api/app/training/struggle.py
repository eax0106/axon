"""Teaching suggestions from real calls: where the employee fell short, in the words of the call."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.calls.analysis import Struggle, _norm
from app.models import Call, Employee, KnowledgeKind, SuggestionStatus, TrainingSuggestion

MAX_OPEN = 50  # per employee: an owner who never looks should not collect an unbounded list
KEY_LEN = 400  # the quote_key column; folding can lengthen a 200-character quote a little


def quote_key(quote: str) -> str:
    """The quote as it is compared with the ones already shown."""
    return _norm(quote)[:KEY_LEN]


async def store(
    session: AsyncSession, call: Call, employee: Employee, struggles: list[Struggle]
) -> int:
    """Keep the struggles of a real call as open suggestions; returns how many were new. A test
    call is the owner's own practice, not a real caller. A moment the owner has already seen (the
    same caller words) is not added again."""
    if call.is_test or not struggles:
        return 0
    # A moment the owner already saw (taught or dismissed) is not put in front of them again.
    # Only the new quotes are looked up, not every suggestion the employee ever had.
    keys = {quote_key(item.caller_quote) for item in struggles}
    seen = set(
        await session.scalars(
            select(TrainingSuggestion.quote_key).where(
                TrainingSuggestion.employee_id == employee.id,
                TrainingSuggestion.quote_key.in_(keys),
            )
        )
    )
    waiting = await count_open(session, employee.id)
    added = 0
    for item in struggles:
        key = quote_key(item.caller_quote)
        if waiting + added >= MAX_OPEN or key in seen:
            continue
        seen.add(key)
        session.add(
            TrainingSuggestion(
                account_id=call.account_id,
                employee_id=employee.id,
                call_id=call.id,
                kind=KnowledgeKind(item.kind),
                reason=item.reason,
                caller_quote=item.caller_quote,
                quote_key=key,
                agent_quote=item.agent_quote,
                text=item.text,
            )
        )
        added += 1
    return added


async def count_open(session: AsyncSession, employee_id: uuid.UUID) -> int:
    return (
        await session.scalar(
            select(func.count())
            .select_from(TrainingSuggestion)
            .where(
                TrainingSuggestion.employee_id == employee_id,
                TrainingSuggestion.status == SuggestionStatus.OPEN,
            )
        )
        or 0
    )
