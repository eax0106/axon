"""What an employee was taught: facts and rules (put in every prompt) and documents (searched).

Taught items apply to the next call at once. They are not part of the published script, so they
have no publish step, no versions and no restore.
"""

import unicodedata
import uuid

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.employees.compiler import Knowledge, printable
from app.models import Employee, KnowledgeDoc, KnowledgeItem, KnowledgeKind
from app.providers.base import EmbeddingProvider, ProviderKind
from app.providers.registry import require

MAX_FACTS, MAX_RULES, MAX_ITEM = 60, 20, 300  # all of them go into every prompt
MAX_DOCS = 10
MIN_SCORE = 0.55  # shortcut: a first guess for Gemini's cosine scores; tune on real documents
TOP_K = 3
LIMITS = {KnowledgeKind.FACT: MAX_FACTS, KnowledgeKind.RULE: MAX_RULES}


def clean_text(value: str) -> str:
    """One line of printable text: a taught item is never a heading, a list or hidden text."""
    return " ".join(printable(value).split())


def _key(kind: KnowledgeKind, value: str) -> tuple[KnowledgeKind, str]:
    return kind, unicodedata.normalize("NFKC", value).casefold()


class NewItem(BaseModel):
    kind: KnowledgeKind
    text: str = Field(min_length=1, max_length=MAX_ITEM)
    source: str = Field(default="text", pattern="^(text|voice|photo|suggestion)$")

    @field_validator("text")
    @classmethod
    def _clean(cls, value: str) -> str:
        cleaned = clean_text(value)
        if not cleaned:
            raise ValueError("write something")
        return cleaned


async def lock(session: AsyncSession, employee_id: uuid.UUID) -> None:
    """Serialise the writers of one employee's training, so the caps hold under parallel taps."""
    await session.execute(select(Employee.id).where(Employee.id == employee_id).with_for_update())


async def items_of(session: AsyncSession, employee_id: uuid.UUID) -> list[KnowledgeItem]:
    rows = await session.scalars(
        select(KnowledgeItem)
        .where(KnowledgeItem.employee_id == employee_id)
        .order_by(KnowledgeItem.created_at, KnowledgeItem.id)
    )
    return list(rows)


async def add_items(
    session: AsyncSession, employee: Employee, new: list[NewItem]
) -> list[KnowledgeItem]:
    """Save reviewed items; one already taught (same words) is skipped. 409 when a cap is full.
    Commits."""
    await lock(session, employee.id)
    existing = await items_of(session, employee.id)
    seen = {_key(i.kind, i.text) for i in existing}
    saved: list[KnowledgeItem] = []
    for item in new:
        if _key(item.kind, item.text) in seen:
            continue
        seen.add(_key(item.kind, item.text))
        row = KnowledgeItem(
            account_id=employee.account_id,
            employee_id=employee.id,
            kind=item.kind,
            text=item.text,
            source=item.source,
        )
        saved.append(row)
    for kind, limit in LIMITS.items():
        held = sum(i.kind is kind for i in existing) + sum(i.kind is kind for i in saved)
        if held > limit:
            await session.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"an employee can hold {limit} {kind}s: remove some first"
            )
    session.add_all(saved)
    await session.commit()
    return saved


async def load(session: AsyncSession, employee_id: uuid.UUID) -> Knowledge:
    """What goes into the prompt of the employee's next call."""
    items = await items_of(session, employee_id)
    has_documents = await session.scalar(
        select(KnowledgeDoc.id).where(KnowledgeDoc.employee_id == employee_id).limit(1)
    )
    return Knowledge(
        facts=tuple(i.text for i in items if i.kind is KnowledgeKind.FACT),
        rules=tuple(i.text for i in items if i.kind is KnowledgeKind.RULE),
        documents=has_documents is not None,
    )


class Passage(BaseModel):
    document: str
    text: str
    score: float


# The score is the dot product of two unit vectors, taken inside Postgres. Chunks embedded at
# another size (the model was changed) are left out, not compared.
# shortcut: every chunk of the employee is scored on each look-up (10 documents of 100 passages
# at most); move to a pgvector column with an HNSW index when documents grow past that.
_SEARCH = text(
    """
    SELECT d.name AS document, c.text AS text, c.score AS score
    FROM (
        SELECT doc_id, text,
               (SELECT sum(x * y) FROM unnest(embedding, CAST(:q AS real[])) AS t(x, y)) AS score
        FROM knowledge_chunks
        WHERE employee_id = :employee AND cardinality(embedding) = :dim
    ) c
    JOIN knowledge_docs d ON d.id = c.doc_id
    WHERE c.score >= :min_score
    ORDER BY c.score DESC
    LIMIT :k
    """
)


async def passages(
    session: AsyncSession, employee_id: uuid.UUID, question: list[float], k: int = TOP_K
) -> list[Passage]:
    """The passages of this employee's documents that are close in meaning to the question and
    close enough to be worth saying; nothing when no document is relevant."""
    rows = await session.execute(
        _SEARCH,
        {
            "q": question,
            "employee": employee_id,
            "dim": len(question),
            "min_score": MIN_SCORE,
            "k": k,
        },
    )
    return [Passage(document=r.document, text=r.text, score=float(r.score)) for r in rows]


def embedder() -> EmbeddingProvider:
    provider = require(ProviderKind.EMBEDDING)
    assert isinstance(provider, EmbeddingProvider)
    return provider


async def look_up(session: AsyncSession, employee_id: uuid.UUID, question: str) -> list[Passage]:
    [vector] = await embedder().embed([question], query=True)
    return await passages(session, employee_id, vector)
