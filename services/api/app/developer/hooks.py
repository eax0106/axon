"""Announce a new lead and a campaign's change of status from the one place every path passes:
the flush. A change made anywhere (an API request, the worker, a callback) is announced in the
same transaction, and a path added later cannot forget to.

A Core insert (`insert(Lead)`) never reaches the flush, so a path that makes leads that way has to
announce them itself; the campaign runner does."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.developer import events, shapes
from app.models import Campaign, Lead


@event.listens_for(Session, "before_flush")
def announce(session: Session, _context: object, _instances: object) -> None:
    now = datetime.now(UTC)
    for obj in list(session.new):
        if isinstance(obj, Lead):
            obj.id = obj.id or uuid.uuid4()
            data = {"lead": shapes.lead_out(obj, now).model_dump(mode="json")}
            events.record(session, obj.account_id, events.LEAD_CREATED, data)
    for obj in list(session.dirty):
        if isinstance(obj, Campaign):
            changed = inspect(obj).attrs.status.history
            if changed.added and changed.deleted and changed.added[0] != changed.deleted[0]:
                data = {
                    "campaign": shapes.campaign_out(obj, obj.created_at).model_dump(mode="json"),
                    "previous_status": changed.deleted[0].value,
                }
                events.record(session, obj.account_id, events.CAMPAIGN_STATUS, data)
