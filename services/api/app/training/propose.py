"""Turn what the owner says, types or photographs into a proposal of facts and rules.

The model only proposes. Nothing is stored here: the owner reviews the list and saves what is
right (`POST .../training/items`), so a model that misheard or misread cannot teach the employee.
"""

from fastapi import HTTPException
from pydantic import BaseModel

from app.employees.ai import ROLE, ask, llm
from app.providers.base import FileReader, FileUnreadError, ProviderKind, ProviderNotConfiguredError
from app.training.knowledge import MAX_ITEM, NewItem, clean_text

MAX_PROPOSED = 30
READ_FILE = (
    "Write out, as plain text, all the text in this file exactly as written. Keep every name, "
    "price, number, date and unit. A table becomes one line per row. Do not add, describe or "
    "explain anything. If there is no readable text, reply with the single word NONE."
)
SPLIT_PROMPT = (
    ROLE + " The owner is teaching the employee. Split what they give you into separate items. "
    "A FACT is something true about the business that a caller may ask about: a price, hours, an "
    "address, a policy, a product detail. A RULE is how the employee must behave: what to always "
    "or never say or do, or what to say when something comes up. One idea per item, in the "
    "language of the text and as close to the owner's own words as you can, at most "
    f"{MAX_ITEM - 50} characters each. Never add anything the text does not say. Skip filler. "
    'JSON: {"items": [{"kind": "fact or rule", "text": "..."}]}'
)


class Proposal(BaseModel):
    items: list[NewItem]
    dropped: int = 0  # too long or malformed to keep: the owner is told to say it again, shorter


async def split(text: str, source: str) -> Proposal:
    """Facts and rules in `text`, for the owner to review."""
    data = await ask(SPLIT_PROMPT, f"Text:\n{text}")
    raw = data.get("items")
    items: list[NewItem] = []
    dropped = 0
    for entry in raw[:MAX_PROPOSED] if isinstance(raw, list) else []:
        try:
            items.append(NewItem(kind=entry["kind"], text=entry["text"], source=source))
        except (KeyError, TypeError, ValueError):  # not a fact or a rule, or too long
            dropped += 1
    return Proposal(items=items, dropped=dropped)


def file_reader() -> FileReader:
    provider = llm()
    if not isinstance(provider, FileReader):
        raise ProviderNotConfiguredError(
            ProviderKind.LLM, provider.name, [], f"{provider.name} cannot read photos or PDFs"
        )
    return provider


async def text_of(data: bytes, mime: str) -> str:
    """The text in a photo or PDF, read by the model."""
    try:
        read = await file_reader().read_file(data, mime, READ_FILE)
    except FileUnreadError as exc:
        raise HTTPException(
            422, "the whole file could not be read: send a shorter file or split it"
        ) from exc
    text = clean_text_keep_lines(read)
    if not text or text.upper() == "NONE":
        raise HTTPException(422, "no readable text found in that file")
    return text


def clean_text_keep_lines(value: str) -> str:
    """Line breaks mean something in a price list (one row per line); other controls do not."""
    return "\n".join(line for line in (clean_text(x) for x in value.splitlines()) if line)
