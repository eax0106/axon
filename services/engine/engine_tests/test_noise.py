"""Noise on the line: barge-ins that were not the caller are counted, and the voice activity
detector is tunable with today's values as defaults."""

import asyncio

import pytest
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    Frame,
    InterruptionFrame,
    TranscriptionFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import FramePushed
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from engine import vad
from engine.events import CallObserver


async def _nothing(_: object) -> None:
    pass


def _feed(observer: CallObserver, *frames: Frame) -> None:
    source = FrameProcessor()
    for frame in frames:
        pushed = FramePushed(
            source=source,
            destination=source,
            frame=frame,
            direction=FrameDirection.DOWNSTREAM,
            timestamp=0,
        )
        asyncio.run(observer.on_push_frame(pushed))


def said(text: str) -> TranscriptionFrame:
    return TranscriptionFrame(text=text, user_id="caller", timestamp="")


def test_a_barge_in_with_under_two_words_after_it_counts_as_false() -> None:
    observer = CallObserver(_nothing, FrameProcessor())
    _feed(
        observer,
        BotStartedSpeakingFrame(),
        InterruptionFrame(),  # a horn: nothing was said
        UserStoppedSpeakingFrame(),
        BotStoppedSpeakingFrame(),
        BotStartedSpeakingFrame(),
        InterruptionFrame(),
        said("haan"),  # one word
        UserStoppedSpeakingFrame(),
        BotStoppedSpeakingFrame(),
        BotStartedSpeakingFrame(),
        InterruptionFrame(),
        said("wait, what is"),
        said("the price?"),  # the caller really had something to say
        UserStoppedSpeakingFrame(),
        BotStoppedSpeakingFrame(),
    )
    event = observer.usage.as_event()
    assert (event["interruptions"], event["false_interruptions"]) == (3, 2)


def test_an_interruption_while_the_bot_is_quiet_is_not_a_barge_in() -> None:
    observer = CallObserver(_nothing, FrameProcessor())
    _feed(observer, InterruptionFrame(), UserStoppedSpeakingFrame(), said("hello"))
    assert (observer.usage.interruptions, observer.usage.false_interruptions) == (0, 0)


def test_the_detector_keeps_todays_values_unless_set(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in vad.SETTINGS:
        monkeypatch.delenv(name, raising=False)
    today = vad.analyzer().params
    assert (today.confidence, today.start_secs, today.stop_secs, today.min_volume) == (
        0.7,
        0.2,
        0.2,
        0.6,
    )
    monkeypatch.setenv("AXON_VAD_START_SECS", "0.35")
    monkeypatch.setenv("AXON_VAD_CONFIDENCE", "0.8")
    tuned = vad.analyzer().params
    assert (tuned.start_secs, tuned.confidence, tuned.stop_secs) == (0.35, 0.8, 0.2)


@pytest.mark.parametrize("value", ["fast", "0", "3", "-0.2"])
def test_a_wrong_setting_fails_at_start_up(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("AXON_VAD_START_SECS", value)
    with pytest.raises(ValueError, match="AXON_VAD_START_SECS"):
        vad.params()
