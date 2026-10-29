"""Provider interfaces. Each outside service is one adapter against the vendor's real API."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import ClassVar, TypedDict


class ProviderKind(StrEnum):
    TELEPHONY = "telephony"
    STT = "stt"
    LLM = "llm"
    EMBEDDING = "embedding"
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


@dataclass(frozen=True)
class CallDetail:
    answered: bool  # someone picked up and talked (talk time above zero)
    duration_s: int  # ring plus talk
    talk_s: int
    hangup_cause: str  # the carrier's own word, for example USER_BUSY


class ChatMessage(TypedDict):
    role: str  # "user" or "assistant"
    content: str


class TelephonyProvider(Provider):
    kind = ProviderKind.TELEPHONY

    @abstractmethod
    async def originate(
        self, from_number: str, to_number: str, answer_url: str, hangup_url: str | None = None
    ) -> str:
        """Place an outbound call; the carrier fetches `answer_url` when it is answered and
        calls `hangup_url` when it ends. Returns the carrier's call id."""

    @abstractmethod
    def callback_is_authentic(self, url: str, headers: Mapping[str, str]) -> bool:
        """Whether a call-end callback to `url` really came from the carrier (its signature)."""

    @abstractmethod
    async def call_detail(self, call_uuid: str) -> "CallDetail | None":
        """How a finished call went (the carrier's record), or None if it is not available yet."""

    @abstractmethod
    async def is_live(self, call_uuid: str) -> bool:
        """Whether the carrier has this call up right now."""

    @abstractmethod
    async def live_parties(self, call_uuid: str) -> tuple[str, str] | None:
        """The caller's and the called number of a call the carrier has up right now, as the
        carrier itself records them, or None when it has no such live call."""

    @abstractmethod
    async def hang_up(self, call_uuid: str) -> None:
        """End the call; a call that already ended is not an error."""

    @abstractmethod
    async def ensure_application(self, name: str, answer_url: str, hangup_url: str) -> str:
        """Register what the carrier should fetch when a call arrives on a number routed to it
        (`answer_url` returns the call's instructions, `hangup_url` hears of its end). Returns the
        carrier's id for it."""

    @abstractmethod
    async def route_number(self, e164: str, application_id: str) -> None:
        """Send incoming calls on a number we hold to that application. Repeating it is fine."""

    @abstractmethod
    async def transfer(self, call_uuid: str, instructions_url: str) -> None:
        """Move the caller of a live call to new instructions fetched from `instructions_url`."""


class ObjectStorageProvider(Provider):
    kind = ProviderKind.STORAGE

    @abstractmethod
    async def put(self, key: str, data: bytes, content_type: str) -> None:
        """Store `data` at `key`, replacing anything there."""

    @abstractmethod
    def presigned_url(self, key: str, ttl_s: int = 900) -> str:
        """A time-limited link that reads the object at `key` without credentials."""


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


class FileUnreadError(Exception):
    """The model did not give back everything in the file (the reply was cut off or blocked), so
    what it did return must not be used: a price cut in the middle is a wrong price."""


class FileReader(ABC):
    """What a model offers beyond chat: reading a photo or a PDF. A mixin for the LLM adapter of
    a vendor whose model takes files."""

    name: ClassVar[str]

    @abstractmethod
    async def read_file(self, data: bytes, mime: str, instruction: str) -> str:
        """Follow `instruction` about the image or PDF in `data`; returns the model's whole text,
        or raises FileUnreadError."""


class EmbeddingProvider(Provider):
    kind = ProviderKind.EMBEDDING

    @abstractmethod
    async def embed(self, texts: list[str], *, query: bool = False) -> list[list[float]]:
        """One unit-length vector per text, in order. `query` marks a search question, whose
        vector is made differently from a passage's."""


class TextToSpeechProvider(Provider):
    kind = ProviderKind.TTS

    @abstractmethod
    async def synthesize(self, text: str, voice_id: str, language: str, speed: float) -> bytes:
        """Speak `text` with the vendor's voice `voice_id`; returns a WAV (16 kHz mono)."""


@dataclass(frozen=True)
class Order:
    id: str  # the vendor's id for the payment order


@dataclass(frozen=True)
class PaymentInfo:
    order_id: str
    amount_paise: int
    captured: bool  # the money has been taken (authorized-only payments are not credited)


class PaymentProvider(Provider):
    kind = ProviderKind.PAYMENTS

    @abstractmethod
    async def fetch_payment(self, payment_id: str) -> PaymentInfo:
        """What the vendor itself says about a payment: the browser's word is not enough."""

    @abstractmethod
    async def create_order(self, amount_paise: int, receipt: str) -> Order:
        """Open an order for `amount_paise` (INR) that the customer then pays in the checkout."""

    @abstractmethod
    def public_key(self) -> str:
        """The key id the browser checkout needs (never the secret)."""

    @abstractmethod
    def checkout_is_authentic(self, order_id: str, payment_id: str, signature: str) -> bool:
        """Whether the browser's checkout result is signed by the vendor for this order."""

    @abstractmethod
    def webhook_is_authentic(self, body: bytes, headers: Mapping[str, str]) -> bool:
        """Whether a webhook body is signed by the vendor (checked on the raw bytes)."""


@dataclass(frozen=True)
class InventoryNumber:
    e164: str
    number_type: str  # regular, 140 or 1600
    setup_fee: Decimal
    monthly_fee: Decimal  # the carrier's own price, not what we charge


class NumberStore(ABC):
    """What a carrier offers beyond calling: a stock of numbers to buy and give back. A mixin for
    the telephony adapter of a carrier that sells numbers."""

    name: ClassVar[str]

    @abstractmethod
    async def search_numbers(
        self, search: str = "", page: int = 1, per_page: int = 20
    ) -> list[InventoryNumber]:
        """Numbers on sale whose digits contain `search`."""

    @abstractmethod
    async def buy_number(self, e164: str) -> str:
        """Buy one number from the stock for the account; returns the carrier's reference."""

    @abstractmethod
    async def release_number(self, e164: str) -> None:
        """Give a number back to the stock; one the carrier no longer holds is not an error."""


@dataclass(frozen=True)
class DigilockerStart:
    url: str  # where the holder gives consent
    ref: str


@dataclass(frozen=True)
class PanResult:
    verified: bool
    name: str  # the name the tax records hold
    holder_ref: str  # the carrier's id for this holder


class NumberKycProvider(Provider):
    kind = ProviderKind.NUMBER_KYC

    @abstractmethod
    async def verify_pan(self, pan: str, name: str) -> PanResult:
        """Check a PAN against the holder's name. The PAN is not kept by us."""

    @abstractmethod
    async def digilocker_start(self, holder_ref: str, redirect_url: str) -> DigilockerStart:
        """Begin the Aadhaar check: the holder consents in DigiLocker."""

    @abstractmethod
    async def digilocker_verified(self, holder_ref: str, ref: str) -> bool:
        """Whether the holder has finished the DigiLocker consent for `ref`."""


class EmailProvider(Provider):
    kind = ProviderKind.EMAIL

    @abstractmethod
    async def send(self, to: str, subject: str, text: str) -> None:
        """Send a plain-text email from the platform's own address."""


class LeadSourceProvider(Provider):
    kind = ProviderKind.LEADS


class SheetsProvider(Provider):
    kind = ProviderKind.SHEETS

    @abstractmethod
    async def append_row(
        self, refresh_token: str, sheet_id: str, cell_range: str, row: list[str]
    ) -> None:
        """Add one row under the data in a sheet range. Values are stored as text, never parsed."""

    @abstractmethod
    async def exchange_code(self, code: str, redirect_uri: str) -> str:
        """Trade a consent code for a refresh token the account can be read with later."""

    @abstractmethod
    async def read_rows(
        self, refresh_token: str, sheet_id: str, cell_range: str
    ) -> list[list[str]]:
        """The rows of a sheet range, header first."""


@dataclass(frozen=True)
class OAuthGrant:
    refresh_token: str
    scopes: frozenset[str]  # what the user actually allowed, which can be less than was asked for


@dataclass(frozen=True)
class Busy:
    start: datetime
    end: datetime


class CalendarProvider(Provider):
    kind = ProviderKind.CALENDAR

    @abstractmethod
    async def exchange_code(self, code: str, redirect_uri: str) -> OAuthGrant:
        """Trade a consent code for a refresh token; one consent covers Calendar and Sheets."""

    @abstractmethod
    async def revoke(self, refresh_token: str) -> None:
        """Take the permission back at the vendor."""

    @abstractmethod
    async def busy(
        self, refresh_token: str, calendar_id: str, start: datetime, end: datetime
    ) -> list[Busy]:
        """When the calendar is taken between `start` and `end`."""

    @abstractmethod
    async def create_event(
        self,
        refresh_token: str,
        calendar_id: str,
        event_id: str,
        title: str,
        description: str,
        start: datetime,
        end: datetime,
    ) -> bool:
        """Put an event on the calendar under the caller's own `event_id`; False when that id is
        already there (the same booking made twice). Nobody is invited."""

    @abstractmethod
    async def delete_event(self, refresh_token: str, calendar_id: str, event_id: str) -> None:
        """Remove an event; one already gone is not an error."""


class WhatsAppProvider(Provider):
    kind = ProviderKind.WHATSAPP

    @abstractmethod
    async def send_template(
        self, to_e164: str, name: str, language: str, params: list[str], recipient_name: str
    ) -> None:
        """Send an approved template to one number; raises if the vendor refuses it."""
