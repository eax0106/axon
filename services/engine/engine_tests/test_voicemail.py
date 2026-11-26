"""A machine that picks up an outbound call is caught while the call is on: the call hangs up, is
marked voicemail with the words heard, and goes back on the retry ladder. Every doubt is a
person."""

import asyncio
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from pipecat.classifiers.base_classifier import (
    BaseClassifier,
    ChoiceResult,
    ClassifierImage,
    ClassifierQuestion,
    ClassifierResult,
)
from pipecat.extensions.voicemail.voicemail_detector import VOICEMAIL_QUESTION
from pipecat.frames.frames import (
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.metrics.metrics import LLMTokenUsage
from pipecat.pipeline.pipeline import Pipeline
from pipecat.tests.utils import SleepFrame, run_test
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from tests.conftest import sql

from app.instant import dialer
from app.models import Call, CallStatus
from engine import voicemail
from engine.voicemail import CallVoicemail, LeanToConversation

from .test_call_records import fetch, new_call, recorder, world

__all__ = ["world"]
QUESTION = {"voicemail": VOICEMAIL_QUESTION}


class _Says(BaseClassifier):
    """An LLM classifier stand-in with a fixed answer, or one that fails."""

    def __init__(self, choice: str = "", confidence: float = 0.0) -> None:
        super().__init__()
        self.choice_, self.confidence = choice, confidence

    async def _ask(
        self,
        state: str | dict[str, Any] | list[Any],
        questions: Mapping[str, ClassifierQuestion],
        images: Sequence[ClassifierImage] = (),
    ) -> tuple[dict[str, ClassifierResult], LLMTokenUsage | None]:
        if not self.choice_:
            raise TimeoutError("no answer")
        result = ChoiceResult(choice=self.choice_, probabilities={}, confidence=self.confidence)
        return {name: result for name in questions}, None


def verdict(classifier: BaseClassifier, text: str) -> str:
    return asyncio.run(classifier.choice(text, QUESTION))["voicemail"].choice


@pytest.mark.parametrize(
    "text",
    [
        "The number you are calling is switched off",
        "आप जिस नंबर पर कॉल कर रहे हैं वह अभी पहुंच से बाहर है",
        "మీరు కాల్ చేస్తున్న నంబర్ ప్రస్తుతం స్విచ్ ఆఫ్ చేయబడి ఉంది",
        "Please leave your message after the beep",
    ],
)
def test_an_operator_announcement_is_voicemail_without_asking_the_llm(text: str) -> None:
    assert verdict(LeanToConversation(_Says()), text) == "voicemail"


def test_without_a_phrase_the_llm_decides_but_only_when_sure() -> None:
    hello = "Hello? Who is this?"
    assert verdict(LeanToConversation(_Says("voicemail", 0.95)), hello) == "voicemail"
    assert verdict(LeanToConversation(_Says("voicemail", 0.6)), hello) == "conversation"
    assert verdict(LeanToConversation(_Says("conversation", 0.9)), hello) == "conversation"
    assert verdict(LeanToConversation(_Says()), hello) == "conversation"  # failed: a person
    assert verdict(LeanToConversation(None), hello) == "conversation"  # no Sarvam key


def test_without_the_sarvam_key_only_the_phrase_list_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    assert voicemail.sarvam_classifier("te") is None
    monkeypatch.setenv("SARVAM_API_KEY", "test-key")
    assert voicemail.sarvam_classifier("te") is not None


def _pickup(monkeypatch: pytest.MonkeyPatch, words: str) -> tuple[list[str], list[type]]:
    """The callee says `words`, then is quiet; the bot's reply is ready meanwhile."""
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    heard: list[str] = []

    async def hang_up(quote: str) -> None:
        heard.append(quote)

    detector = CallVoicemail("en", hang_up)
    reply = [TTSStartedFrame(), TTSAudioRawFrame(b"\0\0" * 160, 16000, 1), TTSStoppedFrame()]
    down, _ = asyncio.run(
        run_test(
            Pipeline([detector.detector(), detector.gate()]),
            frames_to_send=[
                UserStartedSpeakingFrame(),
                TranscriptionFrame(text=words, user_id="callee", timestamp=""),
                UserStoppedSpeakingFrame(),
                *reply,
                SleepFrame(sleep=1.5),  # the decision comes 1 s after the callee stops
            ],
        )
    )
    return heard, [type(f) for f in down]


def test_a_machine_is_hung_up_on_with_its_words_and_the_bot_never_speaks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    heard, frames = _pickup(monkeypatch, "The number you are calling is switched off")
    assert heard == ["The number you are calling is switched off"]
    assert TTSAudioRawFrame not in frames


def test_a_person_hears_the_reply_once_the_decision_is_made(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    heard, frames = _pickup(monkeypatch, "Hello, who is this?")
    assert heard == [] and TTSAudioRawFrame in frames


def test_a_voicemail_call_is_marked_and_put_back_on_the_retry_ladder(
    world: tuple[str, Any, Any],
) -> None:
    url = world[0]
    call = new_call(world, status="in_progress")

    async def machine(r: Any) -> None:
        await r.voicemail()
        await r.finished("voicemail", None)

    recorder(url, call, machine)
    got = fetch(url, call)
    assert got["status"] == "completed" and got["voicemail"] is True
    assert sql(url, "SELECT count(*) FROM calls") == 2
    retry = "SELECT {} FROM calls WHERE id <> :c"
    assert sql(url, retry.format("status"), {"c": call}) == "queued"
    assert sql(url, retry.format("attempt"), {"c": call}) == 2
    voiced = "SELECT data->>'reason' FROM call_events WHERE type = 'ended' AND call_id = :c"
    assert sql(url, voiced, {"c": call}) == "voicemail"


def test_the_carriers_callback_settling_first_still_retries_a_voicemail(
    world: tuple[str, Any, Any],
) -> None:
    url = world[0]
    call = new_call(world, status="in_progress")
    recorder(url, call, lambda r: r.voicemail())

    async def callback() -> None:
        db = create_async_engine(url)
        async with async_sessionmaker(db)() as session:
            row = await session.get(Call, call)
            assert row is not None
            await dialer.settle(session, row, CallStatus.COMPLETED, datetime.now(UTC), 9)
            await session.commit()
        await db.dispose()

    asyncio.run(callback())
    assert sql(url, "SELECT count(*) FROM calls WHERE status = 'queued'") == 1
