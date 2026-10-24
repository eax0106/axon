"""Provider interfaces. Each outside service is one adapter against the vendor's real API."""

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import ClassVar, TypedDict


class ProviderKind(StrEnum):
    TELEPHONY = "telephony"
    STT = "stt"
    LLM = "llm"
    TTS = "tts"
    PAYMENTS = "payments"
    STORAGE = "storage"
    EMAIL = "email"
    WHATSAPP = "whatsapp"
    CALENDAR = "calendar"
    SHEETS = "sheets"
    LEADS = "leads"
    NUMBER_KYC = "number_kyc"


class ProviderNotConfiguredError(Exception):
    def __init__(self, kind: ProviderKind, name: str, missing_keys: list[str], detail: str):
        super().__init__(detail)
        self.kind, self.name, self.missing_keys, self.detail = kind, name, missing_keys, detail


class Provider(ABC):
    """Base for every adapter.

    ponytail: kind-specific interfaces are added by the phase that builds their first real
    adapter (B2 telephony and storage, B3 speech and LLM, ...).
    """

    kind: ClassVar[ProviderKind]
    name: ClassVar[str]

    @abstractmethod
    async def health(self) -> None:
        """Make one cheap authenticated call to the vendor; raise if it fails."""


class ChatMessage(TypedDict):
    role: str  # "user" or "assistant"
    content: str


class TelephonyProvider(Provider):
    kind = ProviderKind.TELEPHONY

    @abstractmethod
    async def originate(self, from_number: str, to_number: str, answer_url: str) -> str:
        """Place an outbound call; the carrier fetches `answer_url` when it is answered.
        Returns the carrier's call id."""

    @abstractmethod
    async def is_live(self, call_uuid: str) -> bool:
        """Whether the carrier has this call up right now."""

    @abstractmethod
    async def hang_up(self, call_uuid: str) -> None:
        """End the call; a call that already ended is not an error."""


class ObjectStorageProvider(Provider):
    kind = ProviderKind.STORAGE

    @abstractmethod
    async def put(self, key: str, data: bytes, content_type: str) -> None:
        """Store `data` at `key`, replacing anything there."""


class SpeechToTextProvider(Provider):
    kind = ProviderKind.STT

    @abstractmethod
    async def transcribe(self, wav: bytes, language: str) -> str:
        """Transcribe a short WAV clip (16 kHz mono) spoken in `language` (te, hi or en)."""


class LLMProvider(Provider):
    kind = ProviderKind.LLM

    @abstractmethod
    async def complete(
        self, system: str, messages: list[ChatMessage], *, json_output: bool = False
    ) -> str:
        """One chat completion; with `json_output` the reply is a JSON document."""


class TextToSpeechProvider(Provider):
    kind = ProviderKind.TTS

    @abstractmethod
    async def synthesize(self, text: str, voice_id: str, language: str, speed: float) -> bytes:
        """Speak `text` with the vendor's voice `voice_id`; returns a WAV (16 kHz mono)."""
