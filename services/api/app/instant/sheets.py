"""Take new rows from each connected Google Sheet and run them through intake."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.instant import intake
from app.models import Employee, LeadConnection
from app.providers.base import SheetsProvider


async def poll_connection(
    session: AsyncSession, connection: LeadConnection, sheets: SheetsProvider, now: datetime
) -> int:
    """New rows since the cursor, header first: the header row names the fields. Returns how many
    rows were taken. ponytail: the cursor moves after each row's own commit, so a crash between
    the two can offer one row twice; the intake dedupe window absorbs it."""
    if not (connection.google_refresh_token and connection.sheet_id and connection.sheet_range):
        return 0
    rows = await sheets.read_rows(
        connection.google_refresh_token, connection.sheet_id, connection.sheet_range
    )
    if len(rows) < 2 or len(rows) <= connection.sheet_cursor:
        return 0
    header = rows[0]
    employee = await session.get(Employee, connection.employee_id)
    assert employee is not None  # FK guarantees it
    taken = 0
    for row in rows[max(connection.sheet_cursor, 1) :]:
        await intake.process(
            session, employee, dict(zip(header, row, strict=False)), source="sheets", now=now
        )
        connection.sheet_cursor += 1
        await session.commit()
        taken += 1
    return taken


async def poll_all(
    factory: async_sessionmaker[AsyncSession], sheets: SheetsProvider, now: datetime
) -> int:
    async with factory() as session:
        ids = list(
            await session.scalars(
                select(LeadConnection.id).where(LeadConnection.sheet_id.is_not(None))
            )
        )
    total = 0
    for connection_id in ids:
        async with factory() as session:
            connection = await session.get(LeadConnection, connection_id)
            if connection is not None:
                total += await poll_connection(session, connection, sheets, now)
    return total
