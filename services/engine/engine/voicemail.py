"""Voicemail and operator announcements on outbound calls, caught while the call is on.

Pipecat's VoicemailDetector reads what the other side says first and holds the bot's speech until
it decides. In India most machine pickups are the operator's announcement ("switched off", "not
reachable") in Telugu, Hindi or English, so a fixed phrase list decides first; anything else is
asked of the Sarvam LLM. Dropping a person is the costly mistake, so every doubt is a
conversation: the LLM must be sure (MIN_CONFIDENCE), and a failed or slow answer is a person.
On a voicemail verdict the call hangs up and is marked `voicemail` with the words heard; the retry
ladder calls back (app.instant.dialer.settle).
"""

import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from pipecat.classifiers.base_classifier import (
    BaseClassifier,
    ChoiceResult,
    ClassifierImage,
    ClassifierQuestion,
    ClassifierResult,
)
from pipecat.classifiers.llm.classifier import LLMClassifier
from pipecat.extensions.voicemail.voicemail_detector import VoicemailDetector
from pipecat.metrics.metrics import LLMTokenUsage

from app.providers.base import ProviderKind
from engine.services import SERVICES, Delivery

# Words only a machine says when a call is picked up: the operators' recorded announcements and
# the end of a voicemail greeting. Words a person might also say ("not available", "leave a
# message") are left to the LLM. Our own list; the Telugu and Hindi wait for the native-speaker
# check (WIRING_CHECKLIST). Matched in lower case.
PHRASES = (
    "switched off",
    "not reachable",
    "out of coverage",
    "is not in service",
    "does not exist",
    "please try again later",
    "after the beep",
    "after the tone",
    "स्विच ऑफ",
    "स्विच ऑफ़",
    "स्विच्ड ऑफ",
    "पहुंच से बाहर",
    "पहुँच से बाहर",
    "कवरेज क्षेत्र से बाहर",
    "कृपया थोड़ी देर बाद",
    "స్విచ్ ఆఫ్",
    "స్విచ్ఛాఫ్",
    "పరిధికి వెలుపల",
    "కవరేజ్ ఏరియా",
    "కొంత సమయం తర్వాత ప్రయత్నించండి",
)
MIN_CONFIDENCE = 0.8  # the LLM's "voicemail" counts only when it is at least this sure
LLM_TIMEOUT_S = 2.0  # a person's first reply waits on this: a slow answer counts as a person
VOICEMAIL, CONVERSATION = "voicemail", "conversation"


def heard_phrase(text: str) -> str | None:
    lowered = text.lower()
    return next((phrase for phrase in PHRASES if phrase in lowered), None)


def _verdict(choice: str, confidence: float) -> ChoiceResult:
    other = CONVERSATION if choice == VOICEMAIL else VOICEMAIL
    return ChoiceResult(
        choice=choice,
        probabilities={choice: confidence, other: round(1 - confidence, 3)},
        confidence=confidence,
    )


class LeanToConversation(BaseClassifier):
    """The phrase list, then the LLM (if any); "voicemail" only when sure."""

    def __init__(self, llm: BaseClassifier | None) -> None:
        super().__init__()
        self._llm = llm

    async def _ask(
        self,
        state: str | dict[str, Any] | list[Any],
        questions: Mapping[str, ClassifierQuestion],
        images: Sequence[ClassifierImage] = (),
    ) -> tuple[dict[str, ClassifierResult], LLMTokenUsage | None]:
        if heard_phrase(str(state)):
            return {name: _verdict(VOICEMAIL, 1.0) for name in questions}, None
        if self._llm is None:
            return {name: _verdict(CONVERSATION, 1.0) for name in questions}, None
        try:
            results = await self._llm.choice(state, questions)  # type: ignore[arg-type]
        except Exception:  # any failure: a person, never a hang-up
            return {name: _verdict(CONVERSATION, 1.0) for name in questions}, None
        sure: dict[str, ClassifierResult] = {}
        for name, result in results.items():
            machine = result.choice == VOICEMAIL and result.confidence >= MIN_CONFIDENCE
            sure[name] = result if machine else _verdict(CONVERSATION, 1 - result.confidence)
        return sure, None


def sarvam_classifier(language: str) -> BaseClassifier | None:
    """An LLM classifier on Sarvam's model, or None without its key (the phrase list only)."""
    if not os.environ.get("SARVAM_API_KEY"):
        return None
    llm = SERVICES[(ProviderKind.LLM, "sarvam")](language, Delivery())
    return LLMClassifier(llm=llm, timeout=LLM_TIMEOUT_S)  # type: ignore[arg-type]


class CallVoicemail(VoicemailDetector):
    """Acts at the verdict itself: an operator's announcement repeats without a pause, so
    waiting for the greeting to go quiet (Pipecat's `on_voicemail_detected`) may never end."""

    def __init__(self, language: str, on_voicemail: Callable[[str], Awaitable[None]]) -> None:
        super().__init__(classifier=LeanToConversation(sarvam_classifier(language)))
        self._on_voicemail = on_voicemail

    async def _decide(self, label: Any) -> None:
        await super()._decide(label)
        if label == VOICEMAIL:
            await self._on_voicemail(" ".join(self._transcript)[:300])
