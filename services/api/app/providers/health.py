"""Live health of each vendor, scored from what calls and dials have just seen.

A failure is recorded when a call leaves a vendor (it failed over, or the leg had nothing left)
and when the carrier fails a dial; a success for each vendor that served a call to its end and for
each dial the carrier took. A vendor is unhealthy while, over the last `WINDOW`, it has at least
`MIN_FAILURES` failures and they are half or more of its outcomes. Unhealthy vendors are tried
last when a call starts, and the dialers start no call while a leg has no healthy vendor. Once
its failures age out the vendor is healthy again and gets traffic back (a half-open breaker).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import ProviderOutcome

WINDOW = timedelta(minutes=10)
MIN_FAILURES = 3
KEEP = timedelta(days=7)  # what the admin console can still show


@dataclass(frozen=True)
class Score:
    kind: str
    vendor: str
    ok: int
    failed: int

    @property
    def healthy(self) -> bool:
        return not (self.failed >= MIN_FAILURES and self.failed * 2 >= self.ok + self.failed)

    @property
    def success_rate(self) -> float | None:
        total = self.ok + self.failed
        return round(self.ok / total, 3) if total else None


def record(session: AsyncSession, kind: str, vendor: str, *, ok: bool, at: datetime) -> None:
    """Add one outcome; the caller commits."""
    session.add(ProviderOutcome(kind=str(kind), vendor=vendor, ok=ok, at=at))


async def scores(session: AsyncSession, now: datetime) -> dict[tuple[str, str], Score]:
    rows = await session.execute(
        select(
            ProviderOutcome.kind,
            ProviderOutcome.vendor,
            func.count().filter(ProviderOutcome.ok),
            func.count().filter(~ProviderOutcome.ok),
        )
        .where(ProviderOutcome.at > now - WINDOW, ProviderOutcome.at <= now)
        .group_by(ProviderOutcome.kind, ProviderOutcome.vendor)
    )
    return {(k, v): Score(k, v, ok, failed) for k, v, ok, failed in rows}


async def unhealthy(session: AsyncSession, now: datetime) -> frozenset[tuple[str, str]]:
    """(kind, vendor) pairs that are unhealthy right now."""
    return frozenset(
        key for key, score in (await scores(session, now)).items() if not score.healthy
    )


async def prune(factory: async_sessionmaker[AsyncSession], now: datetime) -> int:
    async with factory() as session:
        result = await session.execute(
            delete(ProviderOutcome).where(ProviderOutcome.at < now - KEEP)
        )
        await session.commit()
        return int(result.rowcount)  # type: ignore[attr-defined]
