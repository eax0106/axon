"""The whole Postgres schema. Later phases add columns through new migrations.

ponytail: fast-moving per-feature settings (script bundles, dialer and inbound settings,
campaign options) live in JSONB columns until a phase needs to query or constrain them.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

Credits = Numeric(14, 4)  # 1 credit = ₹1; four decimals for per-second metering


def _enum(cls: type[StrEnum], name: str) -> SAEnum:
    # Stored as text with a CHECK constraint: adding a value later is an ALTER on one constraint,
    # not a Postgres enum type change.
    return SAEnum(
        cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda e: [m.value for m in e],
    )


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def _account_fk() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)


class Role(StrEnum):
    """A user's role inside their own account. Platform staff is a separate flag on User."""

    OWNER = "owner"
    MEMBER = "member"


class Channel(StrEnum):
    INSTANT = "instant"
    BULK = "bulk"
    INBOUND = "inbound"


class EmployeeStatus(StrEnum):
    DRAFT = "draft"
    TRAINING = "training"
    LIVE = "live"
    PAUSED = "paused"


class Purpose(StrEnum):
    PROMOTIONAL = "promotional"
    SERVICE = "service"
    TRANSACTIONAL = "transactional"


class VoiceTier(StrEnum):
    VALUE = "value"
    STANDARD = "standard"
    PREMIUM = "premium"


class NumberType(StrEnum):
    REGULAR = "regular"
    SERIES_140 = "140"
    SERIES_1600 = "1600"


class NumberStatus(StrEnum):
    ACTIVE = "active"
    GRACE = "grace"
    RELEASED = "released"


class Direction(StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class CallStatus(StrEnum):
    QUEUED = "queued"
    RINGING = "ringing"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    NO_ANSWER = "no_answer"
    BUSY = "busy"
    FAILED = "failed"
    CANCELED = "canceled"


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELED = "canceled"


class ContactStatus(StrEnum):
    PENDING = "pending"
    CALLING = "calling"
    CALLBACK = "callback"
    DONE = "done"
    EXHAUSTED = "exhausted"
    SKIPPED = "skipped"
    CANCELED = "canceled"


class DncSource(StrEnum):
    MANUAL = "manual"
    BULK = "bulk"
    CALLER_REQUEST = "caller_request"


class ConsentScope(StrEnum):
    CAMPAIGN = "campaign"
    LEAD_SOURCE = "lead_source"


class LedgerKind(StrEnum):
    TOPUP = "topup"
    CALL = "call"
    NUMBER = "number"
    REFUND = "refund"
    BONUS = "bonus"
    ADJUSTMENT = "adjustment"


class PaymentStatus(StrEnum):
    CREATED = "created"
    PAID = "paid"
    FAILED = "failed"


class DeliveryStatus(StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(200))
    business_name: Mapped[str | None] = mapped_column(String(200))
    # Callers are remembered across calls (a short note on the lead) unless the owner turns it off.
    caller_memory: Mapped[bool] = mapped_column(server_default="true")
    created_at: Mapped[datetime] = _created()


class User(Base):
    __tablename__ = "users"
    __table_args__ = (Index("uq_users_email_lower", func.lower(text("email")), unique=True),)
    id: Mapped[uuid.UUID] = _pk()
    account_id: Mapped[uuid.UUID] = _account_fk()
    email: Mapped[str] = mapped_column(String(320))
    password_hash: Mapped[str] = mapped_column(String(255))
    ui_prefs: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default="{}"
    )  # remembered filters
    role: Mapped[Role] = mapped_column(_enum(Role, "user_role"), default=Role.OWNER)
    # ALTERX staff: admin console, provider health, impersonation. Never set through the API.
    is_platform_admin: Mapped[bool] = mapped_column(server_default=text("false"))
    created_at: Mapped[datetime] = _created()


class Voice(Base):
    __tablename__ = "voices"
    __table_args__ = (UniqueConstraint("provider", "provider_voice_id"),)
    id: Mapped[uuid.UUID] = _pk()
    provider: Mapped[str] = mapped_column(String(50))
    provider_voice_id: Mapped[str] = mapped_column(String(200))
    tier: Mapped[VoiceTier] = mapped_column(_enum(VoiceTier, "voice_tier"))
    public_name: Mapped[str] = mapped_column(String(100))
    native_language: Mapped[str] = mapped_column(String(10))
    accent: Mapped[str | None] = mapped_column(String(50))
    tone_tags: Mapped[list[str]] = mapped_column(ARRAY(String(50)), server_default="{}")
    language_scores: Mapped[dict[str, float]] = mapped_column(JSONB, server_default="{}")


class PhoneNumber(Base):
    __tablename__ = "numbers"
    __table_args__ = (
        CheckConstraint("channels >= 1", name="channels_positive"),
        # Released numbers keep their row (history) and the same number can be bought again.
        Index(
            "uq_numbers_e164_held",
            "e164",
            unique=True,
            postgresql_where=text("status <> 'released'"),
        ),
    )
    id: Mapped[uuid.UUID] = _pk()
    account_id: Mapped[uuid.UUID] = _account_fk()
    provider: Mapped[str] = mapped_column(String(50))
    e164: Mapped[str] = mapped_column(String(20))
    number_type: Mapped[NumberType] = mapped_column(_enum(NumberType, "number_type"))
    channels: Mapped[int] = mapped_column(server_default="1")
    status: Mapped[NumberStatus] = mapped_column(_enum(NumberStatus, "number_status"))
    renews_on: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = _created()


class Employee(Base):
    __tablename__ = "employees"
    id: Mapped[uuid.UUID] = _pk()
    account_id: Mapped[uuid.UUID] = _account_fk()
    name: Mapped[str] = mapped_column(String(100))
    role_title: Mapped[str | None] = mapped_column(String(200))
    channel: Mapped[Channel] = mapped_column(_enum(Channel, "channel"))
    purpose: Mapped[Purpose] = mapped_column(_enum(Purpose, "purpose"))
    status: Mapped[EmployeeStatus] = mapped_column(
        _enum(EmployeeStatus, "employee_status"), default=EmployeeStatus.DRAFT
    )
    language: Mapped[str] = mapped_column(String(10))
    extra_languages: Mapped[list[str]] = mapped_column(ARRAY(String(10)), server_default="{}")
    voice_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("voices.id", ondelete="SET NULL"))
    number_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("numbers.id", ondelete="SET NULL"), unique=True
    )
    # The editable script bundle. What calls use is the newest row in employee_versions.
    draft: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    # Voice, ambience, toggles and capture fields: applied to live calls immediately, no publish.
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    # Instant dialer rules (window, delay, out-of-window rule, retry ladder); see instant/rules.py.
    dialer: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class EmployeeVersion(Base):
    __tablename__ = "employee_versions"
    __table_args__ = (UniqueConstraint("employee_id", "version"),)
    id: Mapped[uuid.UUID] = _pk()
    employee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int]
    bundle: Mapped[dict[str, Any]] = mapped_column(JSONB)
    published_at: Mapped[datetime] = _created()


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (UniqueConstraint("account_id", "phone"),)
    id: Mapped[uuid.UUID] = _pk()
    account_id: Mapped[uuid.UUID] = _account_fk()
    phone: Mapped[str] = mapped_column(String(20))
    name: Mapped[str | None] = mapped_column(String(200))
    fields: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    memory: Mapped[str | None] = mapped_column(Text)  # what earlier calls taught us, if remembered
    created_at: Mapped[datetime] = _created()


class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[uuid.UUID] = _pk()
    account_id: Mapped[uuid.UUID] = _account_fk()
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    # Overrides the employee's purpose for this campaign when set (DECISIONS: purpose rule table).
    purpose: Mapped[Purpose | None] = mapped_column(_enum(Purpose, "purpose"))
    status: Mapped[CampaignStatus] = mapped_column(
        _enum(CampaignStatus, "campaign_status"), default=CampaignStatus.DRAFT
    )
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    created_at: Mapped[datetime] = _created()


class CampaignContact(Base):
    __tablename__ = "campaign_contacts"
    __table_args__ = (UniqueConstraint("campaign_id", "phone"),)
    id: Mapped[uuid.UUID] = _pk()
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), index=True
    )
    phone: Mapped[str] = mapped_column(String(20))
    variables: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    status: Mapped[ContactStatus] = mapped_column(
        _enum(ContactStatus, "contact_status"), default=ContactStatus.PENDING
    )
    attempts: Mapped[int] = mapped_column(server_default="0")


class Call(Base):
    __tablename__ = "calls"
    __table_args__ = (
        Index("ix_calls_queue", "status", "scheduled_for"),
        Index("ix_calls_account_created", "account_id", "created_at"),
        Index("ix_calls_analysis", "analysis_status"),
    )
    id: Mapped[uuid.UUID] = _pk()
    account_id: Mapped[uuid.UUID] = _account_fk()
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), index=True
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("leads.id", ondelete="SET NULL"), index=True
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("campaigns.id", ondelete="SET NULL"), index=True
    )
    number_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("numbers.id", ondelete="SET NULL")
    )
    direction: Mapped[Direction] = mapped_column(_enum(Direction, "direction"))
    channel: Mapped[Channel] = mapped_column(_enum(Channel, "channel"))
    status: Mapped[CallStatus] = mapped_column(
        _enum(CallStatus, "call_status"), default=CallStatus.QUEUED
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_s: Mapped[int | None]
    credits_charged: Mapped[Decimal] = mapped_column(Credits, server_default="0")
    outcome: Mapped[str | None] = mapped_column(String(50))
    sentiment: Mapped[str | None] = mapped_column(String(20))
    summary: Mapped[str | None] = mapped_column(Text)
    transcript: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default="[]")
    captured: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    recording_key: Mapped[str | None] = mapped_column(String(500))
    # Test calls (phone, browser) are free and excluded from stats and billing.
    is_test: Mapped[bool] = mapped_column(server_default="false")
    # The post-call job: NULL = not applicable yet, then
    # pending -> analysing -> done | skipped | failed.
    analysis_status: Mapped[str | None] = mapped_column(String(20))
    analysis_error: Mapped[str | None] = mapped_column(String(200))
    analysis_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_callback: Mapped[bool] = mapped_column(server_default="false")  # the caller asked for it
    # Dialer queue: a queued call with scheduled_for NULL is held until someone redials it.
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt: Mapped[int] = mapped_column(server_default="1")
    # The carrier's id for the dial request, and for the call itself once it reports one (the
    # call-end callback carries both; the carrier's record is keyed by the call id).
    carrier_call_id: Mapped[str | None] = mapped_column(String(100), index=True)
    carrier_leg_id: Mapped[str | None] = mapped_column(String(100), index=True)
    created_at: Mapped[datetime] = _created()


class IntakeStatus(StrEnum):
    ACCEPTED = "accepted"
    DEDUPLICATED = "deduplicated"
    REJECTED = "rejected"


class LeadConnection(Base):
    """An Instant employee's lead sources: the private intake URL and secret, Meta and Sheets."""

    __tablename__ = "lead_connections"
    id: Mapped[uuid.UUID] = _pk()  # the public part of the intake URL
    account_id: Mapped[uuid.UUID] = _account_fk()
    employee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), unique=True
    )
    # Stored as written because the owner can reveal it again; compared in constant time.
    secret: Mapped[str] = mapped_column(String(64))
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    meta_form_id: Mapped[str | None] = mapped_column(String(50), unique=True)
    meta_page_token: Mapped[str | None] = mapped_column(Text)
    sheet_id: Mapped[str | None] = mapped_column(String(100))
    sheet_range: Mapped[str | None] = mapped_column(String(100))
    google_refresh_token: Mapped[str | None] = mapped_column(Text)
    sheet_cursor: Mapped[int] = mapped_column(server_default="0")  # rows already taken, header too
    created_at: Mapped[datetime] = _created()


class LeadIntakeEntry(Base):
    __tablename__ = "lead_intake_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[uuid.UUID] = _account_fk()
    employee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("employees.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(20))  # website, meta, sheets, manual, test
    status: Mapped[IntakeStatus] = mapped_column(_enum(IntakeStatus, "intake_status"))
    reason: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(20))
    lead_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"))
    call_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("calls.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _created()


class Note(Base):
    """A note on a call or a lead (or both: a call note also shows on its lead)."""

    __tablename__ = "notes"
    id: Mapped[uuid.UUID] = _pk()
    account_id: Mapped[uuid.UUID] = _account_fk()
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), index=True
    )
    call_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("calls.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class CallEvent(Base):
    __tablename__ = "call_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    call_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("calls.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(50))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    at: Mapped[datetime] = _created()


class DncEntry(Base):
    __tablename__ = "dnc_entries"
    __table_args__ = (UniqueConstraint("account_id", "phone"),)
    id: Mapped[uuid.UUID] = _pk()
    account_id: Mapped[uuid.UUID] = _account_fk()
    phone: Mapped[str] = mapped_column(String(20))
    source: Mapped[DncSource] = mapped_column(_enum(DncSource, "dnc_source"))
    reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = _created()


class ConsentAttestation(Base):
    __tablename__ = "consent_attestations"
    id: Mapped[uuid.UUID] = _pk()
    account_id: Mapped[uuid.UUID] = _account_fk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    scope: Mapped[ConsentScope] = mapped_column(_enum(ConsentScope, "consent_scope"))
    subject_id: Mapped[uuid.UUID]  # the campaign or lead source the attestation covers
    statement: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class WalletEntry(Base):
    __tablename__ = "wallet_ledger"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[uuid.UUID] = _account_fk()
    kind: Mapped[LedgerKind] = mapped_column(_enum(LedgerKind, "ledger_kind"))
    amount: Mapped[Decimal] = mapped_column(Credits)
    balance_after: Mapped[Decimal] = mapped_column(Credits)
    ref_type: Mapped[str | None] = mapped_column(String(50))
    ref_id: Mapped[str | None] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = _created()


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[uuid.UUID] = _pk()
    account_id: Mapped[uuid.UUID] = _account_fk()
    provider: Mapped[str] = mapped_column(String(50))
    provider_order_id: Mapped[str] = mapped_column(String(100), unique=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(100))
    amount_inr: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    status: Mapped[PaymentStatus] = mapped_column(
        _enum(PaymentStatus, "payment_status"), default=PaymentStatus.CREATED
    )
    created_at: Mapped[datetime] = _created()


class ApiKey(Base):
    __tablename__ = "api_keys"
    id: Mapped[uuid.UUID] = _pk()
    account_id: Mapped[uuid.UUID] = _account_fk()
    name: Mapped[str] = mapped_column(String(100))
    prefix: Mapped[str] = mapped_column(String(16))
    key_hash: Mapped[str] = mapped_column(String(128), unique=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class WebhookEndpoint(Base):
    __tablename__ = "webhook_endpoints"
    id: Mapped[uuid.UUID] = _pk()
    account_id: Mapped[uuid.UUID] = _account_fk()
    url: Mapped[str] = mapped_column(String(2000))
    # ponytail: plaintext because signing needs it back; B12 decides on encryption at rest.
    secret: Mapped[str] = mapped_column(String(100))
    events: Mapped[list[str]] = mapped_column(ARRAY(String(50)))
    created_at: Mapped[datetime] = _created()


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    id: Mapped[uuid.UUID] = _pk()
    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("webhook_endpoints.id", ondelete="CASCADE"), index=True
    )
    event: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[DeliveryStatus] = mapped_column(
        _enum(DeliveryStatus, "delivery_status"), default=DeliveryStatus.PENDING
    )
    attempts: Mapped[int] = mapped_column(server_default="0")
    response_code: Mapped[int | None]
    created_at: Mapped[datetime] = _created()
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[uuid.UUID] = _pk()
    account_id: Mapped[uuid.UUID] = _account_fk()
    kind: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class AuditEntry(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    impersonator_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(100))
    target_type: Mapped[str | None] = mapped_column(String(50))
    target_id: Mapped[str | None] = mapped_column(String(100))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    created_at: Mapped[datetime] = _created()
