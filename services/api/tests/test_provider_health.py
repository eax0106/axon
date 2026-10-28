"""Vendor health scored from recent outcomes, against a real database."""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from app.providers import health

from .helpers import run_db

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


def add(url: str, kind: str, vendor: str, ok: bool, count: int, ago: timedelta) -> None:
    async def work(factory: Any) -> None:
        async with factory() as session:
            for _ in range(count):
                health.record(session, kind, vendor, ok=ok, at=NOW - ago)
            await session.commit()

    run_db(url, work)


def down(url: str, now: datetime = NOW) -> frozenset[tuple[str, str]]:
    async def work(factory: Any) -> frozenset[tuple[str, str]]:
        async with factory() as session:
            return await health.unhealthy(session, now)

    return run_db(url, work)  # type: ignore[no-any-return]


def scores(url: str) -> dict[tuple[str, str], health.Score]:
    async def work(factory: Any) -> dict[tuple[str, str], health.Score]:
        async with factory() as session:
            return await health.scores(session, NOW)

    return run_db(url, work)  # type: ignore[no-any-return]


def test_a_vendor_is_unhealthy_with_three_failures_making_half_its_recent_outcomes(
    db_client: TestClient, migrated_url: str
) -> None:
    minute = timedelta(minutes=1)
    add(migrated_url, "tts", "cartesia", False, 2, minute)
    assert down(migrated_url) == frozenset()  # two failures are not a pattern yet
    add(migrated_url, "tts", "cartesia", False, 1, minute)
    assert down(migrated_url) == {("tts", "cartesia")}
    add(migrated_url, "tts", "cartesia", True, 3, minute)
    assert down(migrated_url) == {("tts", "cartesia")}  # 3 of 6: still half
    add(migrated_url, "tts", "cartesia", True, 1, minute)
    assert down(migrated_url) == frozenset()  # 3 of 7: mostly working
    assert scores(migrated_url)[("tts", "cartesia")].success_rate == round(4 / 7, 3)


def test_vendors_are_scored_per_kind(db_client: TestClient, migrated_url: str) -> None:
    add(migrated_url, "stt", "sarvam", False, 3, timedelta(minutes=2))
    add(migrated_url, "tts", "sarvam", True, 5, timedelta(minutes=2))
    assert down(migrated_url) == {("stt", "sarvam")}


def test_failures_age_out_and_the_vendor_gets_traffic_again(
    db_client: TestClient, migrated_url: str
) -> None:
    add(migrated_url, "llm", "gemini", False, 5, timedelta(minutes=9))
    assert down(migrated_url) == {("llm", "gemini")}
    assert down(migrated_url, NOW + timedelta(minutes=2)) == frozenset()
    add(migrated_url, "llm", "gemini", False, 3, timedelta(minutes=20))
    assert down(migrated_url, NOW + timedelta(minutes=2)) == frozenset()  # all too old


def test_outcomes_older_than_a_week_are_pruned(db_client: TestClient, migrated_url: str) -> None:
    add(migrated_url, "stt", "smallest", True, 2, timedelta(days=8))
    add(migrated_url, "stt", "smallest", True, 1, timedelta(days=6))
    assert run_db(migrated_url, lambda factory: health.prune(factory, NOW)) == 2
    assert run_db(migrated_url, lambda factory: health.prune(factory, NOW)) == 0
