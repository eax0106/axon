"""Keyset pages: newest first, a cursor that names the last row seen."""

import base64
import binascii
import uuid
from datetime import datetime

from fastapi import HTTPException
from pydantic import BaseModel

MAX_LIMIT = 100


class Page[T](BaseModel):
    data: list[T]
    next_cursor: str | None  # pass it back as `cursor` for the next page; null on the last page


def encode(created_at: datetime, row_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(f"{created_at.isoformat()}|{row_id}".encode()).decode()


def decode(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        stamp, _, row_id = base64.urlsafe_b64decode(cursor.encode()).decode().partition("|")
        return datetime.fromisoformat(stamp), uuid.UUID(row_id)
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(422, "the cursor is not one this API gave you") from exc
