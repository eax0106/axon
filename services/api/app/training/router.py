"""Teaching an employee: facts and rules (typed, spoken or photographed, reviewed before saving),
documents it can look things up in, and suggestions from its real calls.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.auth import CurrentUser
from app.db import Session
from app.employees.ai import LANGUAGE_NAMES, MAX_AUDIO_BYTES
from app.employees.limits import AiBudget, AiRate
from app.employees.router import load
from app.models import (
    KnowledgeChunk,
    KnowledgeDoc,
    KnowledgeItem,
    KnowledgeKind,
    SuggestionStatus,
    TrainingSuggestion,
)
from app.providers.base import ProviderKind, SpeechToTextProvider
from app.providers.registry import require
from app.training import knowledge, struggle
from app.training.chunks import chunk
from app.training.knowledge import MAX_DOCS, MAX_ITEM, NewItem, clean_text
from app.training.propose import Proposal, clean_text_keep_lines, split, text_of

router = APIRouter()

MAX_FILE_BYTES = 8_000_000  # a phone photo or a PDF
MAX_TEXT_BYTES = 200_000
MAX_TEACH_CHARS = 6000
MAX_DOC_CHARS, MAX_CHUNKS = 60_000, 200  # 60,000 characters in lines of 301+ is under 200
TEXT_TYPES = {"text/plain", "text/markdown", "text/csv"}
FILE_TYPES = {"application/pdf", "image/png", "image/jpeg", "image/webp"}
PHOTO_TYPES = {"image/png", "image/jpeg", "image/webp"}


async def body_of(request: Request, limit: int) -> bytes:
    data = bytearray()
    async for part in request.stream():
        data += part
        if len(data) > limit:
            raise HTTPException(413, f"send up to {limit} bytes")
    if not data:
        raise HTTPException(422, "nothing in the request body")
    return bytes(data)


def content_type(request: Request) -> str:
    return request.headers.get("content-type", "").split(";")[0].strip().lower()


class ItemOut(BaseModel):
    id: uuid.UUID
    kind: KnowledgeKind
    text: str
    source: str
    created_at: datetime


class DocOut(BaseModel):
    id: uuid.UUID
    name: str
    chars: int
    created_at: datetime


class SuggestionOut(BaseModel):
    id: uuid.UUID
    kind: KnowledgeKind
    reason: str
    caller_quote: str
    agent_quote: str | None
    text: str  # empty for a gap: the owner writes the answer
    call_id: uuid.UUID | None
    created_at: datetime


class Training(BaseModel):
    facts: list[ItemOut]
    rules: list[ItemOut]
    documents: list[DocOut]
    open_suggestions: int


def _item(row: KnowledgeItem) -> ItemOut:
    return ItemOut.model_validate(row, from_attributes=True)


@router.get("/employees/{employee_id}/training")
async def get_training(employee_id: uuid.UUID, user: CurrentUser, session: Session) -> Training:
    employee = await load(session, user, employee_id)
    items = await knowledge.items_of(session, employee.id)
    docs = await session.scalars(
        select(KnowledgeDoc)
        .where(KnowledgeDoc.employee_id == employee.id)
        .order_by(KnowledgeDoc.created_at)
    )
    return Training(
        facts=[_item(i) for i in items if i.kind is KnowledgeKind.FACT],
        rules=[_item(i) for i in items if i.kind is KnowledgeKind.RULE],
        documents=[DocOut.model_validate(d, from_attributes=True) for d in docs],
        open_suggestions=await struggle.count_open(session, employee.id),
    )


# --- teaching: propose, review, save ------------------------------------------------------


class TeachText(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEACH_CHARS)


@router.post("/employees/{employee_id}/training/propose", dependencies=[AiBudget])
async def propose_text(
    employee_id: uuid.UUID, body: TeachText, user: CurrentUser, session: Session
) -> Proposal:
    """What the model makes of typed text. Nothing is saved: the owner reviews, then saves."""
    await load(session, user, employee_id)
    return await split(body.text, "text")


class SpokenProposal(Proposal):
    transcript: str


@router.post("/employees/{employee_id}/training/propose-voice", dependencies=[AiBudget])
async def propose_voice(
    employee_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    session: Session,
    language: Annotated[str, Query(pattern="^(te|hi|en)$")] = "en",
) -> SpokenProposal:
    """The request body is one WAV clip (16 kHz mono, up to 2 MB, about a minute)."""
    await load(session, user, employee_id)
    stt = require(ProviderKind.STT)
    assert isinstance(stt, SpeechToTextProvider)
    heard = (await stt.transcribe(await body_of(request, MAX_AUDIO_BYTES), language)).strip()
    if not heard:
        raise HTTPException(422, f"no {LANGUAGE_NAMES[language]} speech heard")
    proposal = await split(heard[:MAX_TEACH_CHARS], "voice")
    return SpokenProposal(items=proposal.items, dropped=proposal.dropped, transcript=heard)


class PhotoProposal(Proposal):
    text: str  # what was read from the photo, so the owner can check it against the picture


@router.post("/employees/{employee_id}/training/propose-photo", dependencies=[AiBudget])
async def propose_photo(
    employee_id: uuid.UUID, request: Request, user: CurrentUser, session: Session
) -> PhotoProposal:
    """The request body is the image (png, jpeg or webp, up to 8 MB), with its content type."""
    await load(session, user, employee_id)
    mime = content_type(request)
    if mime not in PHOTO_TYPES:
        raise HTTPException(415, "send a png, jpeg or webp image")
    read = (await text_of(await body_of(request, MAX_FILE_BYTES), mime))[:MAX_TEACH_CHARS]
    proposal = await split(read, "photo")
    return PhotoProposal(items=proposal.items, dropped=proposal.dropped, text=read)


class Save(BaseModel):
    items: list[NewItem] = Field(min_length=1, max_length=30)


@router.post("/employees/{employee_id}/training/items", status_code=status.HTTP_201_CREATED)
async def save_items(
    employee_id: uuid.UUID, body: Save, user: CurrentUser, session: Session
) -> list[ItemOut]:
    """Save the reviewed list. Applies to the employee's next call. Words already taught are
    skipped."""
    employee = await load(session, user, employee_id)
    return [_item(i) for i in await knowledge.add_items(session, employee, body.items)]


class Edit(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=MAX_ITEM)
    kind: KnowledgeKind | None = None


async def _item_of(session: Session, employee_id: uuid.UUID, item_id: uuid.UUID) -> KnowledgeItem:
    row = await session.scalar(
        select(KnowledgeItem).where(
            KnowledgeItem.id == item_id, KnowledgeItem.employee_id == employee_id
        )
    )
    if row is None:
        raise HTTPException(404, "item not found")
    return row


@router.patch("/employees/{employee_id}/training/items/{item_id}")
async def edit_item(
    employee_id: uuid.UUID, item_id: uuid.UUID, body: Edit, user: CurrentUser, session: Session
) -> ItemOut:
    employee = await load(session, user, employee_id)
    await knowledge.lock(session, employee.id)
    row = await _item_of(session, employee.id, item_id)
    kind = body.kind or row.kind
    if kind is not row.kind:
        held = await session.scalar(
            select(func.count())
            .select_from(KnowledgeItem)
            .where(KnowledgeItem.employee_id == employee.id, KnowledgeItem.kind == kind)
        )
        if (held or 0) >= knowledge.LIMITS[kind]:
            raise HTTPException(409, f"an employee can hold {knowledge.LIMITS[kind]} {kind}s")
    row.kind = kind
    if body.text is not None:
        row.text = clean_text(body.text)
        if not row.text:
            raise HTTPException(422, "write something")
    await session.commit()
    return _item(row)


@router.delete(
    "/employees/{employee_id}/training/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_item(
    employee_id: uuid.UUID, item_id: uuid.UUID, user: CurrentUser, session: Session
) -> None:
    employee = await load(session, user, employee_id)
    await session.delete(await _item_of(session, employee.id, item_id))
    await session.commit()


# --- documents -----------------------------------------------------------------------------


async def _document_text(request: Request) -> str:
    mime = content_type(request)
    if mime in TEXT_TYPES:
        raw = await body_of(request, MAX_TEXT_BYTES)
        try:
            return clean_text_keep_lines(raw.decode("utf-8-sig"))
        except UnicodeDecodeError as exc:
            raise HTTPException(422, "send text as UTF-8") from exc
    if mime in FILE_TYPES:
        return await text_of(await body_of(request, MAX_FILE_BYTES), mime)
    raise HTTPException(415, "send plain text, markdown, CSV, a PDF, or a png, jpeg or webp image")


@router.post(
    "/employees/{employee_id}/training/documents",
    status_code=status.HTTP_201_CREATED,
    dependencies=[AiRate],
)
async def add_document(
    employee_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    session: Session,
    name: Annotated[str, Query(min_length=1, max_length=200)],
) -> DocOut:
    """The request body is the document, with its content type. It is cut into passages and each is
    embedded; if any step fails nothing is stored."""
    employee = await load(session, user, employee_id)
    text = await _document_text(request)
    passages = chunk(text)
    if not passages:
        raise HTTPException(422, "nothing readable in that document")
    if len(text) > MAX_DOC_CHARS or len(passages) > MAX_CHUNKS:
        raise HTTPException(422, f"a document can hold up to {MAX_DOC_CHARS} characters")
    vectors = await knowledge.embedder().embed(passages)
    await knowledge.lock(session, employee.id)
    held = await session.scalar(
        select(func.count())
        .select_from(KnowledgeDoc)
        .where(KnowledgeDoc.employee_id == employee.id)
    )
    if (held or 0) >= MAX_DOCS:
        raise HTTPException(409, f"an employee can hold {MAX_DOCS} documents: remove one first")
    doc = KnowledgeDoc(
        account_id=employee.account_id,
        employee_id=employee.id,
        name=clean_text(name)[:200] or "document",
        chars=len(text),
    )
    session.add(doc)
    await session.flush()
    session.add_all(
        KnowledgeChunk(doc_id=doc.id, employee_id=employee.id, position=i, text=p, embedding=v)
        for i, (p, v) in enumerate(zip(passages, vectors, strict=True))
    )
    await session.commit()
    return DocOut.model_validate(doc, from_attributes=True)


@router.delete(
    "/employees/{employee_id}/training/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_document(
    employee_id: uuid.UUID, doc_id: uuid.UUID, user: CurrentUser, session: Session
) -> None:
    employee = await load(session, user, employee_id)
    doc = await session.scalar(
        select(KnowledgeDoc).where(
            KnowledgeDoc.id == doc_id, KnowledgeDoc.employee_id == employee.id
        )
    )
    if doc is None:
        raise HTTPException(404, "document not found")
    await session.delete(doc)  # its passages go with it (ON DELETE CASCADE)
    await session.commit()


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=300)


class Found(BaseModel):
    document: str
    text: str
    score: float


@router.post("/employees/{employee_id}/training/documents/search", dependencies=[AiRate])
async def search_documents(
    employee_id: uuid.UUID, body: Question, user: CurrentUser, session: Session
) -> list[Found]:
    """Try what the AI would find for a question, so the owner can see their documents work."""
    employee = await load(session, user, employee_id)
    found = await knowledge.look_up(session, employee.id, body.question)
    return [Found(**p.model_dump()) for p in found]


# --- suggestions from real calls -------------------------------------------------------------


def _suggestion(row: TrainingSuggestion) -> SuggestionOut:
    return SuggestionOut.model_validate(row, from_attributes=True)


@router.get("/employees/{employee_id}/training/suggestions")
async def suggestions(
    employee_id: uuid.UUID, user: CurrentUser, session: Session
) -> list[SuggestionOut]:
    employee = await load(session, user, employee_id)
    rows = await session.scalars(
        select(TrainingSuggestion)
        .where(
            TrainingSuggestion.employee_id == employee.id,
            TrainingSuggestion.status == SuggestionStatus.OPEN,
        )
        .order_by(TrainingSuggestion.created_at.desc())
    )
    return [_suggestion(r) for r in rows]


async def _open_suggestion(
    session: Session, employee_id: uuid.UUID, suggestion_id: uuid.UUID
) -> TrainingSuggestion:
    row = await session.scalar(
        select(TrainingSuggestion)
        .where(
            TrainingSuggestion.id == suggestion_id, TrainingSuggestion.employee_id == employee_id
        )
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404, "suggestion not found")
    if row.status is not SuggestionStatus.OPEN:
        raise HTTPException(409, f"that suggestion was already {row.status}")
    return row


class Accept(BaseModel):
    text: str | None = Field(default=None, max_length=MAX_ITEM)  # the owner's wording, if any


@router.post("/employees/{employee_id}/training/suggestions/{suggestion_id}/accept")
async def accept_suggestion(
    employee_id: uuid.UUID,
    suggestion_id: uuid.UUID,
    body: Accept,
    user: CurrentUser,
    session: Session,
) -> dict[str, Any]:
    """Teach it: the owner's text, or the suggestion's own. A gap has no text of its own, so the
    owner must write the answer."""
    employee = await load(session, user, employee_id)
    row = await _open_suggestion(session, employee.id, suggestion_id)
    wording = clean_text(body.text or "") or row.text
    if not wording:
        raise HTTPException(422, "write the answer the employee should give")
    row.status = SuggestionStatus.ACCEPTED
    saved = await knowledge.add_items(
        session, employee, [NewItem(kind=row.kind, text=wording, source="suggestion")]
    )
    return {"taught": [_item(i).model_dump(mode="json") for i in saved]}


@router.post(
    "/employees/{employee_id}/training/suggestions/{suggestion_id}/dismiss",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def dismiss_suggestion(
    employee_id: uuid.UUID, suggestion_id: uuid.UUID, user: CurrentUser, session: Session
) -> None:
    employee = await load(session, user, employee_id)
    (
        await _open_suggestion(session, employee.id, suggestion_id)
    ).status = SuggestionStatus.DISMISSED
    await session.commit()
