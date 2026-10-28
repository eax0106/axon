"""What leaves the system through the public API and the webhooks. These shapes are the contract
developers build on, so they are written out here and not borrowed from the dashboard's: a change
to a screen must never change what an integration receives."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.models import Call, Campaign, Lead


class CallOut(BaseModel):
    id: uuid.UUID
    direction: str  # inbound | outbound
    channel: str  # instant | bulk | inbound
    status: str  # queued | ringing | in_progress | completed | no_answer | busy | failed | canceled
    employee_id: uuid.UUID | None
    lead_id: uuid.UUID | None
    campaign_id: uuid.UUID | None
    phone: str | None  # the person on the call
    attempt: int
    is_callback: bool
    created_at: datetime
    started_at: datetime | None
    answered_at: datetime | None
    ended_at: datetime | None
    duration_s: int | None
    outcome: str | None
    sentiment: str | None
    summary: str | None
    captured: dict[str, Any]
    voicemail: bool
    miss_reason: str | None  # an incoming call nobody answered: why


class CallDetail(CallOut):
    transcript: list[dict[str, Any]]  # [{"role": "user" | "assistant", "text": "..."}]


class LeadOut(BaseModel):
    id: uuid.UUID
    phone: str
    name: str | None
    variables: dict[str, Any]
    created_at: datetime


class CampaignOut(BaseModel):
    id: uuid.UUID
    name: str
    employee_id: uuid.UUID
    status: str  # draft | scheduled | running | paused | completed | canceled
    scheduled_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    note: str | None  # why it is not dialing right now, in plain words
    created_at: datetime


def call_out(call: Call, phone: str | None) -> CallOut:
    return CallOut(
        id=call.id,
        direction=call.direction.value,
        channel=call.channel.value,
        status=call.status.value,
        employee_id=call.employee_id,
        lead_id=call.lead_id,
        campaign_id=call.campaign_id,
        phone=phone,
        attempt=call.attempt,
        is_callback=call.is_callback,
        created_at=call.created_at,
        started_at=call.started_at,
        answered_at=call.answered_at,
        ended_at=call.ended_at,
        duration_s=call.duration_s,
        outcome=call.outcome,
        sentiment=call.sentiment,
        summary=call.summary,
        captured=call.captured or {},
        voicemail=call.voicemail,
        miss_reason=call.miss_reason,
    )


def lead_out(lead: Lead, created_at: datetime) -> LeadOut:
    return LeadOut(
        id=lead.id,
        phone=lead.phone,
        name=lead.name,
        variables=lead.fields or {},
        created_at=created_at,
    )


def campaign_out(campaign: Campaign, created_at: datetime) -> CampaignOut:
    return CampaignOut(
        id=campaign.id,
        name=campaign.name,
        employee_id=campaign.employee_id,
        status=campaign.status.value,
        scheduled_at=campaign.scheduled_at,
        started_at=campaign.started_at,
        completed_at=campaign.completed_at,
        note=campaign.note,
        created_at=created_at,
    )
