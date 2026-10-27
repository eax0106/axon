"""Write what happened on a call into its `calls` row: pickup, transcript, duration, final status.

The row is the call's record; the post-call job on the worker (app.calls.postcall) reads it from
there. The engine only writes what it saw: it never summarises or interprets.
"""

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import case, func, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.models import Call, CallEvent, CallStatus

# How a call ended, as run_call names it. Anything else (an exception name) is a failed call.
COMPLETED_REASONS = {
    "caller_hung_up",
    "agent_ended",
    "max_length",
    "silence",
    "pipeline_finished",
    "transferred",
}
KEPT_EVENTS = {
    "started",
    "interruption",
    "recording_stored",
    "recording_not_stored",
    "usage",
    "transferred",
}
MAX_EVENTS = 500
OPEN = (CallStatus.QUEUED, CallStatus.RINGING, CallStatus.IN_PROGRESS)


class TranscriptBuilder:
    """Turns the live event stream into turns: what the caller said, what the agent said.

    The agent's words arrive a few at a time, so they are gathered until it stops speaking, is
    interrupted, or the caller speaks."""

    def __init__(self) -> None:
        self._turns: list[dict[str, Any]] = []
        self._bot: list[str] = []
        self._bot_at: str | None = None

    def feed(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "user_transcript":
            self._flush_bot()
            text = " ".join(str(event.get("text", "")).split())
            if text:
                self._turns.append({"role": "user", "text": text, "at": _now()})
        elif kind == "bot_text":
            text = str(event.get("text", "")).strip()
            if text:
                self._bot_at = self._bot_at or _now()
                self._bot.append(text)
        elif kind in ("bot_stopped_speaking", "interruption", "ended"):
            self._flush_bot()

    def _flush_bot(self) -> None:
        if self._bot:
            text = " ".join(" ".join(self._bot).split())
            self._turns.append({"role": "assistant", "text": text, "at": self._bot_at})
        self._bot, self._bot_at = [], None

    def turns(self) -> list[dict[str, Any]]:
        self._flush_bot()
        return list(self._turns)


def _now() -> str:
    return datetime.now(UTC).isoformat()


class CallRecorder:
    def __init__(self, db: AsyncEngine, call_id: uuid.UUID) -> None:
        self._factory = async_sessionmaker(db, expire_on_commit=False)
        self.call_id = call_id
        self.transcript = TranscriptBuilder()
        self._events: list[tuple[datetime, dict[str, Any]]] = []
        self._started = time.monotonic()
        self._carrier_id: str | None = None

    def tap(self, event: dict[str, Any]) -> None:
        """Called with every live event of the call."""
        self.transcript.feed(event)
        if event.get("type") in KEPT_EVENTS and len(self._events) < MAX_EVENTS:
            self._events.append((datetime.now(UTC), event))

    def _ours(self) -> list[Any]:
        """Conditions that make a row this recorder's: its id, and, for a carrier call, that the row
        waits for this very carrier call (either of its ids) or has no carrier id yet."""
        where: list[Any] = [Call.id == self.call_id]
        if self._carrier_id is not None:
            where.append(
                (Call.carrier_call_id == self._carrier_id)
                | (Call.carrier_leg_id == self._carrier_id)
                | Call.carrier_call_id.is_(None)
            )
        return where

    async def started(
        self, carrier_call_id: str | None = None, voice_tier: str | None = None
    ) -> None:
        """The call was picked up."""
        self._started = time.monotonic()
        self._carrier_id = carrier_call_id
        async with self._factory() as session:
            await session.execute(
                update(Call)
                .where(*self._ours(), Call.status.in_(OPEN))
                .values(
                    status=CallStatus.IN_PROGRESS,
                    answered_at=func.coalesce(Call.answered_at, func.now()),
                    started_at=func.coalesce(Call.started_at, func.now()),
                    # The stream carries the call's own id; the callback will name the call by it.
                    carrier_leg_id=func.coalesce(Call.carrier_leg_id, carrier_call_id),
                    voice_tier=func.coalesce(Call.voice_tier, voice_tier),
                )
            )
            await session.commit()

    async def finished(self, reason: str, recording_key: str | None) -> None:
        """Write the end of the call.

        The status, end time and duration only change while the call is open (the carrier's callback
        often settles it first). What the engine alone knows (transcript, recording, events, and
        the go-ahead for analysis) is written whatever the status, or it would be lost whenever the
        callback wins the race."""
        status = CallStatus.COMPLETED if reason in COMPLETED_REASONS else CallStatus.FAILED
        turns = self.transcript.turns()
        async with self._factory() as session:
            await session.execute(
                update(Call)
                .where(*self._ours(), Call.status.in_(OPEN))
                .values(
                    status=status,
                    ended_at=func.now(),
                    duration_s=round(time.monotonic() - self._started),
                )
            )
            result = await session.execute(
                update(Call)
                .where(*self._ours())
                .values(
                    transcript=turns,
                    recording_key=recording_key,
                    # Test calls are free and not analysed; real ones wait for the post-call job,
                    # and one already analysed is not sent back to the queue.
                    analysis_status=case(
                        (Call.is_test.is_(True), None),
                        (Call.analysis_status.is_(None), "pending"),
                        else_=Call.analysis_status,
                    ),
                )
            )
            if result.rowcount:  # type: ignore[attr-defined]
                events = [(at, e) for at, e in self._events if e.get("type") != "ended"]
                events.append((datetime.now(UTC), {"type": "ended", "reason": reason}))
                for at, event in events:
                    data = {k: v for k, v in event.items() if k != "type"}
                    session.add(
                        CallEvent(call_id=self.call_id, type=str(event["type"]), data=data, at=at)
                    )
            await session.commit()

    async def abandon(self, reason: str) -> None:
        """Setup failed after the call was claimed: it must not stay in progress."""
        async with self._factory() as session:
            await session.execute(
                update(Call)
                .where(Call.id == self.call_id, Call.status.in_(OPEN))
                .values(status=CallStatus.FAILED, ended_at=func.now())
            )
            session.add(
                CallEvent(call_id=self.call_id, type="setup_failed", data={"reason": reason})
            )
            await session.commit()
