"""Provider interfaces. Each outside service is one adapter against the vendor's real API."""

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import ClassVar


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


class Provider(ABC):
    """Base for every adapter.

    ponytail: kind-specific interfaces (TelephonyProvider, SpeechToTextProvider, ...) are added
    by the phase that builds their first real adapter (B2 telephony, B3 speech and LLM, ...).
    """

    kind: ClassVar[ProviderKind]
    name: ClassVar[str]

    @abstractmethod
    async def health(self) -> None:
        """Make one cheap authenticated call to the vendor; raise if it fails."""
