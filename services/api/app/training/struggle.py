"""Teaching suggestions from real calls: where the employee fell short, in the words of the call."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.calls.analysis import Struggle, _norm
from app.models import Call, Employee, KnowledgeKind, SuggestionStatus, TrainingSuggestion

MAX_OPEN = 50  # per employee: an owner who never looks should not collect an unbounded list


async def store(
    session: AsyncSession, call: Call, employee: Employee, struggles: list[Struggle]
) -> int:
    """Keep the struggles of a real call as open suggestions; returns how many were new. A test
    call is the owner's own practice, not a real caller. A moment the owner has already seen (the
    same caller words) is not added again."""
    if call.is_test or not struggles:
        return 0
    known = (
        await session.execute(
            select(TrainingSuggestion.caller_quote, TrainingSuggestion.status).where(
                TrainingSuggestion.employee_id == employee.id
            )
        )
    ).all()
    # A moment the owner already saw (taught or dismissed) is not put in front of them again.
    seen = {_norm(quote) for quote, _ in known}
    waiting = sum(state is SuggestionStatus.OPEN for _, state in known)
    added = 0
    for item in struggles:
        if waiting + added >= MAX_OPEN or _norm(item.caller_quote) in seen:
            continue
        seen.add(_norm(item.caller_quote))
        session.add(
            TrainingSuggestion(
                account_id=call.account_id,
                employee_id=employee.id,
                call_id=call.id,
                kind=KnowledgeKind(item.kind),
                reason=item.reason,
                caller_quote=item.caller_quote,
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
