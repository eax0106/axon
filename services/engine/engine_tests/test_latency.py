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
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.metrics.metrics import TTFBMetricsData, TurnMetricsData
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


def _verdict(complete: bool) -> MetricsFrame:
    return MetricsFrame(
        data=[
            TurnMetricsData(
                processor="BaseSmartTurn",
                is_complete=complete,
                probability=0.9 if complete else 0.2,
                e2e_processing_time_ms=12,
            )
        ]
    )


def test_each_turn_records_the_turn_detectors_wait_and_whether_the_fallback_ended_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    clock = SimpleNamespace(monotonic=lambda: now[0], time=time.time)
    monkeypatch.setattr(engine.events, "time", clock)
    observer = CallObserver(_nothing, FrameProcessor())

    # Smart Turn hears a finished turn: it ends almost at once.
    _push(observer, VADUserStartedSpeakingFrame())
    now[0] = 101.0
    _push(observer, VADUserStoppedSpeakingFrame(stop_secs=0.2))  # quiet since 100.8
    _push(observer, _verdict(True))
    now[0] = 101.1
    _push(observer, UserStoppedSpeakingFrame())
    # Smart Turn calls a paused question unfinished: only the 2 s silence fallback ends it.
    _push(observer, VADUserStartedSpeakingFrame())
    now[0] = 105.0
    _push(observer, VADUserStoppedSpeakingFrame(stop_secs=0.2))  # quiet since 104.8
    _push(observer, _verdict(False))
    now[0] = 106.85
    _push(observer, UserStoppedSpeakingFrame())
    _push(observer, UserStoppedSpeakingFrame())  # a turn end with no caller speech: not timed

    assert observer.usage.as_event()["turn_ends"] == [
        {"wait_ms": 300, "fallback": False},
        {"wait_ms": 2050, "fallback": True},
    ]


def test_a_pause_the_caller_talks_through_drops_the_earlier_verdict() -> None:
    observer = CallObserver(_nothing, FrameProcessor())

    _push(observer, VADUserStartedSpeakingFrame())
    _push(observer, VADUserStoppedSpeakingFrame(stop_secs=0.2))
    _push(observer, _verdict(False))  # "unfinished", and the caller does go on
    _push(observer, VADUserStartedSpeakingFrame())
    _push(observer, VADUserStoppedSpeakingFrame(stop_secs=0.2))
    _push(observer, _verdict(True))
    _push(observer, UserStoppedSpeakingFrame())

    assert [turn["fallback"] for turn in observer.usage.turn_ends] == [False]


def test_a_test_call_is_tagged_on_its_usage_event() -> None:
    assert CallObserver(_nothing, FrameProcessor(), test=True).usage.as_event()["test"] is True
    assert CallObserver(_nothing, FrameProcessor()).usage.as_event()["test"] is False
