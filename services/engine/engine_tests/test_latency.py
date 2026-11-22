"""Each call records how long the caller waited for every reply, and each leg's first-byte time."""

import asyncio
import time
from types import SimpleNamespace
from typing import Any

import pytest
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    Frame,
    MetricsFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.metrics.metrics import TTFBMetricsData
from pipecat.observers.base_observer import FramePushed
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

import engine.events
from engine.events import CallObserver


async def _nothing(_: dict[str, Any]) -> None:
    pass


def _push(observer: CallObserver, frame: Frame) -> None:
    source = FrameProcessor()
    pushed = FramePushed(
        source=source,
        destination=source,
        frame=frame,
        direction=FrameDirection.DOWNSTREAM,
        timestamp=0,
    )
    asyncio.run(observer.on_push_frame(pushed))


def test_the_wait_runs_from_the_callers_last_sound_to_the_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    clock = SimpleNamespace(monotonic=lambda: now[0], time=time.time)
    monkeypatch.setattr(engine.events, "time", clock)
    observer = CallObserver(_nothing, FrameProcessor())

    _push(observer, BotStartedSpeakingFrame())  # the opening: nobody was waiting for it
    _push(observer, VADUserStartedSpeakingFrame())
    now[0] = 103.0
    _push(observer, VADUserStoppedSpeakingFrame(stop_secs=0.2))  # quiet since 102.8
    now[0] = 103.5
    _push(observer, VADUserStartedSpeakingFrame())  # only a pause: the caller goes on
    now[0] = 104.0
    _push(observer, VADUserStoppedSpeakingFrame(stop_secs=0.2))  # quiet since 103.8
    now[0] = 104.45
    _push(observer, BotStartedSpeakingFrame())
    _push(observer, BotStartedSpeakingFrame())  # the same start seen again: not a second reply

    assert observer.usage.response_ms == [650]
    assert observer.usage.as_event()["response_ms"] == [650]


def test_first_byte_times_are_kept_per_leg() -> None:
    legs = {"llm-1": ("llm", "sarvam"), "tts-1": ("tts", "cartesia")}
    observer = CallObserver(_nothing, FrameProcessor(), vendor_of=legs.get)

    _push(
        observer,
        MetricsFrame(
            data=[
                TTFBMetricsData(processor="llm-1", value=0.41),
                TTFBMetricsData(processor="tts-1", value=0.12),
                TTFBMetricsData(processor="tts-1", value=0.0),  # a request that sent nothing
                TTFBMetricsData(processor="unknown", value=0.3),  # not a vendor leg
            ]
        ),
    )

    assert observer.usage.as_event()["ttfb_ms"] == {"llm": [410], "tts": [120]}
