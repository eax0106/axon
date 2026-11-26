"""Re-encrypt every stored secret under the newest key in AXON_SECRETS_KEY (see app.secretbox).

The encrypted columns are found from the models, so a new secret column is rotated without a
change here. Each table is rewritten in one transaction with its rows locked, so a secret saved
while the rotation runs is not overwritten with its older value.
"""

from typing import Any

from sqlalchemy import Column, Table, Text, select, type_coerce, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from app import models  # noqa: F401 - registers every table on Base.metadata
from app.db import Base
from app.secretbox import EncryptedText, SealedBundle, map_bundle_secrets, reseal
from app.settings import get_settings


def encrypted_columns() -> dict[Table, list[Column[Any]]]:
    found: dict[Table, list[Column[Any]]] = {}
    for table in Base.metadata.sorted_tables:
        cols = [c for c in table.columns if isinstance(c.type, EncryptedText | SealedBundle)]
        if cols:
            found[table] = cols
    return found


def _raw(column: Column[Any]) -> Any:
    """The column as stored, skipping the decrypting type."""
    return type_coerce(column, JSONB if isinstance(column.type, SealedBundle) else Text)


def _resealed(column: Column[Any], value: Any) -> Any:
    if isinstance(column.type, SealedBundle):
        return map_bundle_secrets(value, reseal)
    return reseal(value)


async def rotate_table(conn: AsyncConnection, table: Table, columns: list[Column[Any]]) -> int:
    keys = list(table.primary_key.columns)
    rows = await conn.execute(
        select(*keys, *(_raw(c).label(c.name) for c in columns)).with_for_update()
    )
    changed = 0
    for row in rows.mappings():
        values = {
            c.name: type_coerce(_resealed(c, row[c.name]), _raw(c).type)
            for c in columns
            if row[c.name] is not None
        }
        if values:
            where = [k == row[k.name] for k in keys]
            await conn.execute(update(table).where(*where).values(values))
            changed += 1
    return changed


async def rotate_all(database_url: str | None = None) -> dict[str, int]:
    """Rows rewritten, by table."""
    engine = create_async_engine(database_url or get_settings().database_url)
    counts: dict[str, int] = {}
    try:
        for table, columns in encrypted_columns().items():
            async with engine.begin() as conn:
                counts[table.name] = await rotate_table(conn, table, columns)
    finally:
        await engine.dispose()
    return counts
