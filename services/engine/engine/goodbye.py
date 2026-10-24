"""End-of-call by the AI: say goodbye, then hang up only once the goodbye has finished playing.

The LLM calls the `end_call` function after its goodbye. Hanging up at once would cut the last
words off, because audio is queued at the carrier ahead of the caller's ear. So the gate waits
until the bot is no longer speaking and Vobiz has confirmed (`playedStream`) every utterance
checkpoint we asked for, and hangs up anyway after a timeout so a lost confirmation cannot keep
a call (and its cost) open.
"""

import asyncio
from collections.abc import Awaitable, Callable

from pipecat.frames.frames import Frame, InputTransportMessageFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

SETTLE_S = 0.5  # the goodbye text may still be on its way to the TTS when the function runs
TIMEOUT_S = 15.0


class GoodbyeGate:
    def __init__(
        self,
        end: Callable[[str], Awaitable[None]],
        *,
        settle_s: float = SETTLE_S,
        timeout_s: float = TIMEOUT_S,
    ) -> None:
        self._end = end
        self._settle_s, self._timeout_s = settle_s, timeout_s
        self._issued: set[str] = set()
        self._played: set[str] = set()
        self._speaking = False
        self._task: asyncio.Task[None] | None = None
        self._changed = asyncio.Event()

    def tts_started(self) -> None:
        self._speaking = True
        self._changed.set()

    def checkpoint_issued(self, name: str) -> None:
        self._issued.add(name)
        self._changed.set()

    def tts_stopped(self) -> None:
        self._speaking = False
        self._changed.set()

    def played_stream(self, name: str) -> None:
        self._played.add(name)
        self._changed.set()

    def idle(self) -> bool:
        return not self._speaking and self._issued <= self._played

    async def request_end(self) -> None:
        """The AI wants to end the call. Safe to call more than once."""
        if self._task is None:
            self._task = asyncio.create_task(self._wait_then_end())

    async def _wait_then_end(self) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timeout_s
        await asyncio.sleep(self._settle_s)
        while not self.idle():
            self._changed.clear()
            try:
                await asyncio.wait_for(self._changed.wait(), max(deadline - loop.time(), 0))
            except TimeoutError:
                break
        await self._end("agent_ended")

    def cancel(self) -> None:
        if self._task:
            self._task.cancel()


class PlayedStreamTap(FrameProcessor):
    """Passes everything through and tells the gate which checkpoints Vobiz reports as played."""

    def __init__(self, gate: GoodbyeGate) -> None:
        super().__init__()
        self._gate = gate

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, InputTransportMessageFrame):
            message = frame.message
            if isinstance(message, dict) and message.get("event") == "playedStream":
                self._gate.played_stream(str(message.get("name", "")))
        await self.push_frame(frame, direction)
