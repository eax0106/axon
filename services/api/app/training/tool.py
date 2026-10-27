"""The function that lets the AI look in the employee's documents during a call."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.actions.tools import Tool, guard
from app.employees.compiler import KNOWLEDGE_TOOL
from app.training.knowledge import look_up

TIMEOUT_S = 8.0
MAX_QUESTION = 300


def knowledge_tool(factory: async_sessionmaker[AsyncSession], employee_id: uuid.UUID) -> Tool:
    async def run(args: dict[str, Any]) -> dict[str, Any]:
        question = " ".join(str(args.get("question") or "").split())[:MAX_QUESTION]
        if not question:
            return {"ok": False, "error": "a question is needed"}
        async with factory() as session:
            found = await look_up(session, employee_id, question)
        if not found:
            return {"ok": True, "passages": [], "note": "nothing in the documents covers this"}
        return {
            "ok": True,
            "passages": [{"from": p.document, "text": p.text} for p in found],
        }

    return Tool(
        KNOWLEDGE_TOOL,
        "Look in the business's documents for the answer to the caller's question.",
        {
            "question": {
                "type": "string",
                "description": "What the caller asked, in a full sentence",
            }
        },
        ["question"],
        guard(KNOWLEDGE_TOOL, run, TIMEOUT_S),
        TIMEOUT_S,
    )
