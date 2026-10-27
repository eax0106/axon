"""The six events an account can subscribe to, how one is written down, and what it looks like.

An event is a row written in the same transaction as the change it reports (`record`), so a change
that rolls back announces nothing and a crash never loses one. `delivery.fan_out` turns it into
sends later."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session as SyncSession

from app.models import WebhookEvent

CALL_COMPLETED = "call.completed"
CALL_NOT_CONNECTED = "call.not_connected"
INBOUND_ANSWERED = "call.inbound_answered"
INBOUND_MISSED = "call.inbound_missed"
LEAD_CREATED = "lead.created"
CAMPAIGN_STATUS = "campaign.status_changed"
TEST_PING = "test.ping"  # sent by the test button; nobody subscribes to it

EVENT_TYPES = (
    CALL_COMPLETED,
    CALL_NOT_CONNECTED,
    INBOUND_ANSWERED,
    INBOUND_MISSED,
    LEAD_CREATED,
    CAMPAIGN_STATUS,
)
# The calls an employee's own result webhook is about: the person was reached.
CONNECTED = (CALL_COMPLETED, INBOUND_ANSWERED)

DESCRIPTIONS = {
    CALL_COMPLETED: "An outgoing call was answered and has ended, with its analysis.",
    CALL_NOT_CONNECTED: "An outgoing attempt ended unanswered (no answer, busy, failed).",
    INBOUND_ANSWERED: "An incoming call was answered by an employee and ended, with its analysis.",
    INBOUND_MISSED: "An incoming call was not answered, with the reason.",
    LEAD_CREATED: "A person we had never seen became a lead.",
    CAMPAIGN_STATUS: "A bulk campaign changed status (started, paused, resumed, done, canceled).",
}


def record(
    session: AsyncSession | SyncSession,
    account_id: uuid.UUID,
    type_: str,
    data: dict[str, Any],
    employee_id: uuid.UUID | None = None,
) -> WebhookEvent:
    event = WebhookEvent(
        id=uuid.uuid4(), account_id=account_id, employee_id=employee_id, type=type_, data=data
    )
    session.add(event)
    return event


def envelope(
    event_id: uuid.UUID,
    type_: str,
    created_at: datetime,
    account_id: uuid.UUID,
    data: dict[str, Any],
    *,
    test: bool = False,
) -> dict[str, Any]:
    """The body that is sent. `id` stays the same however often it is sent or resent."""
    body = {
        "id": str(event_id),
        "type": type_,
        "created_at": created_at.astimezone(UTC).isoformat(),
        "account_id": str(account_id),
        "data": data,
    }
    return {**body, "test": True} if test else body


def sample(type_: str) -> dict[str, Any]:
    """An example of `data` for each event, used by the test buttons and shown in the docs."""
    ids = {k: str(uuid.uuid5(uuid.NAMESPACE_URL, f"axon-sample/{k}")) for k in "celdp"}
    when = "2026-01-15T10:30:00+00:00"
    call = {
        "id": ids["c"], "direction": "outbound", "channel": "instant", "status": "completed",
        "employee_id": ids["e"], "lead_id": ids["l"], "campaign_id": None,
        "phone": "+919876543210", "attempt": 1, "is_callback": False, "created_at": when,
        "started_at": when, "answered_at": when, "ended_at": "2026-01-15T10:32:10+00:00",
        "duration_s": 130, "outcome": "interested", "sentiment": "positive",
        "summary": "Asked about the 2BHK price and wants a site visit on Saturday.",
        "captured": {"budget": "80 lakh"}, "voicemail": False, "miss_reason": None,
    }  # fmt: skip
    if type_ == CALL_NOT_CONNECTED:
        call |= {
            "status": "no_answer", "answered_at": None, "duration_s": None, "outcome": None,
            "sentiment": None, "summary": None, "captured": {},
        }  # fmt: skip
    if type_ == INBOUND_ANSWERED:
        call |= {"direction": "inbound", "channel": "inbound"}
    if type_ == INBOUND_MISSED:
        call |= {
            "direction": "inbound", "channel": "inbound", "status": "no_answer",
            "answered_at": None, "duration_s": None, "outcome": None, "sentiment": None,
            "summary": None, "captured": {}, "miss_reason": "the business was closed",
        }  # fmt: skip
    if type_ in (CALL_COMPLETED, CALL_NOT_CONNECTED, INBOUND_ANSWERED, INBOUND_MISSED, TEST_PING):
        return {"call": call}
    if type_ == LEAD_CREATED:
        lead = {
            "id": ids["l"], "phone": "+919876543210", "name": "Asha",
            "variables": {"budget": "80 lakh"}, "created_at": when,
        }  # fmt: skip
        return {"lead": lead}
    campaign = {
        "id": ids["p"], "name": "Diwali offer", "employee_id": ids["e"], "status": "running",
        "scheduled_at": None, "started_at": when, "completed_at": None, "note": None,
        "created_at": when,
    }  # fmt: skip
    return {"campaign": campaign, "previous_status": "scheduled"}
