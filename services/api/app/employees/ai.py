"""AI help for building an employee: follow-up questions, a first draft, flow edits, structuring
pasted text, transcribing a spoken brief, and the chat sandbox. All of it goes through the
selected LLM and speech adapters, so without keys every endpoint answers 503.
"""

import json
import re
import uuid
from dataclasses import replace
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError

from app.actions.schema import mask
from app.auth import CurrentUser
from app.db import Session
from app.employees import runtime, service
from app.employees.limits import AiBudget, AiRate
from app.employees.router import load
from app.employees.script import (
    CaptureField,
    FaqItem,
    ScriptBundle,
    Section,
)
from app.models import Channel
from app.providers.base import ChatMessage, LLMProvider, ProviderKind, SpeechToTextProvider
from app.providers.registry import require
from app.training.knowledge import load as load_knowledge

router = APIRouter()

MAX_AUDIO_BYTES = 2_000_000  # one chunk of a spoken brief: about a minute of 16 kHz mono audio
LANGUAGE_NAMES = {"te": "Telugu", "hi": "Hindi", "en": "English"}

ROLE = (
    "You help a small-business owner set up an AI phone employee. The employee makes or answers "
    "real phone calls, so everything you write is spoken aloud: short plain sentences, no lists "
    "or markdown inside the spoken text. Reply with one JSON document only, nothing around it."
)

QUESTIONS_PROMPT = (
    ROLE + " Read the owner's brief and ask the follow-up questions you need to write a good call "
    "script: the facts a caller will ask for, what counts as success, and when to end the call. "
    "Ask at most 5 short questions and skip anything the brief already answers. "
    'JSON: {"questions": ["...", "..."]}'
)

DRAFT_PROMPT = (
    ROLE + " Write a first draft of the employee from the brief and the owner's answers. Write the "
    "spoken text in the opening language. Keep the call flow to 3 to 7 steps; each step says what "
    "to say or ask and what to do with the answer. Put hard facts the owner gave into the FAQ or "
    "agent information; never invent prices, hours or promises. "
    'JSON: {"name": "a first name", "role_title": "...", "welcome_message": "...", '
    '"agent_information": "...", "sections": [{"title": "...", "body": "..."}], '
    '"end_rules": "...", "faq": [{"question": "...", "answer": "..."}], '
    '"capture": [{"name": "snake_case", "description": "..."}]}'
)

EDIT_PROMPT = (
    ROLE
    + " You are given the employee's current script as JSON and an instruction from the owner. "
    "Apply the instruction and return the whole updated script in exactly the same JSON shape "
    "(keep every field and every section id you do not change). Change only what was asked."
)

STRUCTURE_PROMPT = (
    ROLE
    + " The owner pasted free text that describes how calls should go. Split it into a welcome "
    "message and ordered call-flow steps, moving facts and answers to questions into the FAQ and "
    "end conditions into end_rules. Keep the owner's own wording where possible. "
    'JSON: {"welcome_message": "...", "agent_information": "...", "sections": '
    '[{"title": "...", "body": "..."}], "end_rules": "...", '
    '"faq": [{"question": "...", "answer": "..."}]}'
)

CHAT_NOTE = (
    "\n\n(You are being tested in a text chat instead of on a phone. Answer exactly as you would "
    "on a call, in the same short spoken style.)"
)


class AiOutputError(HTTPException):
    def __init__(self, detail: str) -> None:
        super().__init__(status_code=502, detail=f"ai_output_invalid: {detail}")


def llm() -> LLMProvider:
    provider = require(ProviderKind.LLM)
    assert isinstance(provider, LLMProvider)
    return provider


def parse_json(text: str) -> dict[str, Any]:
    """The JSON object in a model reply, tolerating code fences and a sentence around it."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise AiOutputError("the model did not return a JSON object")
    try:
        parsed = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AiOutputError("the model returned malformed JSON") from exc
    if not isinstance(parsed, dict):
        raise AiOutputError("the model did not return a JSON object")
    return parsed


async def ask(system: str, user: str) -> dict[str, Any]:
    reply = await llm().complete(system, [{"role": "user", "content": user}], json_output=True)
    return parse_json(reply)


class Brief(BaseModel):
    brief: str = Field(min_length=1, max_length=6000)
    channel: Channel
    language: Literal["te", "hi", "en"] = "en"


class Questions(BaseModel):
    questions: list[str] = Field(max_length=5)


@router.post("/ai/brief-questions", dependencies=[AiBudget])
async def brief_questions(body: Brief, _: CurrentUser) -> Questions:
    data = await ask(
        QUESTIONS_PROMPT,
        f"Channel: {body.channel}. Opening language: {LANGUAGE_NAMES[body.language]}.\n\n"
        f"Brief:\n{body.brief}",
    )
    try:
        questions = Questions.model_validate({"questions": data.get("questions")})
    except ValidationError as exc:
        raise AiOutputError("questions were missing or not a list of 5 or fewer") from exc
    return questions


class Answer(BaseModel):
    question: str = Field(max_length=500)
    answer: str = Field(max_length=2000)


class DraftRequest(Brief):
    answers: list[Answer] = Field(default_factory=list, max_length=5)


class Draft(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    role_title: str | None = Field(default=None, max_length=200)
    script: ScriptBundle
    capture: list[CaptureField]


def _script_from(data: dict[str, Any]) -> ScriptBundle:
    allowed = {"welcome_message", "agent_information", "sections", "end_rules", "faq"}
    fields = {k: v for k, v in data.items() if k in allowed}
    try:
        return ScriptBundle(
            **{
                **fields,
                "sections": [Section(**s) for s in fields.get("sections") or []],
                "faq": [FaqItem(**f) for f in fields.get("faq") or []],
            }
        )
    except (ValidationError, TypeError) as exc:
        raise AiOutputError("the script did not match the expected shape") from exc


@router.post("/ai/draft-agent", dependencies=[AiBudget])
async def draft_agent(body: DraftRequest, _: CurrentUser) -> Draft:
    answers = "\n".join(f"Q: {a.question}\nA: {a.answer}" for a in body.answers) or "(none)"
    data = await ask(
        DRAFT_PROMPT,
        f"Channel: {body.channel}. Opening language: {LANGUAGE_NAMES[body.language]}.\n\n"
        f"Brief:\n{body.brief}\n\nOwner's answers:\n{answers}",
    )
    try:
        capture = [CaptureField(**c) for c in data.get("capture") or []]
        return Draft(
            name=str(data.get("name") or "").strip()[:100] or "New employee",
            role_title=(str(data["role_title"])[:200] if data.get("role_title") else None),
            script=_script_from(data),
            capture=capture,
        )
    except (ValidationError, TypeError) as exc:
        raise AiOutputError("the draft did not match the expected shape") from exc


class StructureRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    language: Literal["te", "hi", "en"] = "en"


@router.post("/ai/structure-prompt", dependencies=[AiBudget])
async def structure_prompt(body: StructureRequest, _: CurrentUser) -> ScriptBundle:
    data = await ask(
        STRUCTURE_PROMPT, f"Language: {LANGUAGE_NAMES[body.language]}.\n\nText:\n{body.text}"
    )
    return _script_from(data)


class EditRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=2000)


@router.post("/employees/{employee_id}/ai/edit-flow", dependencies=[AiBudget])
async def edit_flow(
    employee_id: uuid.UUID, body: EditRequest, user: CurrentUser, session: Session
) -> ScriptBundle:
    """A proposed edit of the draft script. Nothing is saved: the client shows it and PUTs it."""
    employee = await load(session, user, employee_id)
    current = service.bundle_of(employee)
    # The actions hold secrets and are not the model's to edit: they stay out of the prompt.
    script = current.model_dump_json(exclude={"actions"})
    data = await ask(EDIT_PROMPT, f"Current script:\n{script}\n\nInstruction:\n{body.instruction}")
    revised = _script_from(data)
    # The model only returns script fields; keep the ones it may not touch.
    return revised.model_copy(
        update={
            "strictness": current.strictness,
            "pre_call_variables": current.pre_call_variables,
            "actions": mask(current.actions),
        }
    )


class Transcript(BaseModel):
    text: str


@router.post("/ai/transcribe-chunk", dependencies=[AiRate])
async def transcribe_chunk(
    request: Request,
    _: CurrentUser,
    language: Annotated[str, Query(pattern="^(te|hi|en)$")] = "en",
) -> Transcript:
    """One chunk of a spoken brief: the request body is the WAV itself (16 kHz mono, up to 2 MB).
    The client joins the text of its chunks."""
    stt = require(ProviderKind.STT)
    assert isinstance(stt, SpeechToTextProvider)
    wav = b""
    async for part in request.stream():
        wav += part
        if len(wav) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "send a WAV chunk of up to 2 MB")
    if not wav:
        raise HTTPException(422, "no audio in the request body")
    return Transcript(text=(await stt.transcribe(wav, language)).strip())


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    messages: list[ChatTurn] = Field(min_length=1, max_length=40)
    source: Literal["draft", "live"] = "draft"


class ChatReply(BaseModel):
    reply: str


@router.post("/employees/{employee_id}/chat", dependencies=[AiBudget])
async def chat(
    employee_id: uuid.UUID, body: ChatRequest, user: CurrentUser, session: Session
) -> ChatReply:
    """Text sandbox: talk to the employee as a caller would. Nothing is stored or billed."""
    employee = await load(session, user, employee_id)
    if body.messages[-1].role != "user":
        raise HTTPException(422, "the last message must be from the caller")
    if body.source == "live":
        live = await service.latest_version(session, employee.id)
        if live is None:
            raise HTTPException(409, "nothing is published yet")
        bundle = ScriptBundle.model_validate(live.bundle)
    else:
        bundle = service.bundle_of(employee)
    # A text chat has no tools, so documents are left out; "Try a question" on the documents
    # shows what the AI would find in them.
    taught = replace(await load_knowledge(session, employee.id), documents=False)
    system = await runtime.prompt_for(session, employee, bundle, knowledge=taught) + CHAT_NOTE
    turns: list[ChatMessage] = [{"role": t.role, "content": t.content} for t in body.messages]
    return ChatReply(reply=(await llm().complete(system, turns)).strip())
