"""An employee's result webhook: where it is set, and its test button."""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth import CurrentUser, not_impersonating
from app.db import Session
from app.developer import delivery, events, result_webhook
from app.developer.result_webhook import ResultWebhook
from app.employees import service
from app.employees.limits import take
from app.employees.router import load

router = APIRouter()
TESTS_PER_HOUR = 30


@router.get("/employees/{employee_id}/webhook")
async def get_webhook(
    employee_id: uuid.UUID, user: CurrentUser, session: Session
) -> dict[str, ResultWebhook | None]:
    employee = await load(session, user, employee_id)
    return {"webhook": result_webhook.mask(service.bundle_of(employee).result_webhook)}


@router.put("/employees/{employee_id}/webhook", dependencies=[Depends(not_impersonating)])
async def put_webhook(
    employee_id: uuid.UUID, body: ResultWebhook, user: CurrentUser, session: Session
) -> dict[str, ResultWebhook | None]:
    """Set the draft's result webhook. It reaches live calls after publish, like the script."""
    employee = await load(session, user, employee_id)
    stored = service.bundle_of(employee)
    try:
        hook = result_webhook.keep_secret(body, stored.result_webhook)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    employee.draft = stored.model_copy(update={"result_webhook": hook}).model_dump()
    await session.commit()
    return {"webhook": result_webhook.mask(hook)}


@router.delete("/employees/{employee_id}/webhook", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(employee_id: uuid.UUID, user: CurrentUser, session: Session) -> None:
    employee = await load(session, user, employee_id)
    stored = service.bundle_of(employee)
    employee.draft = stored.model_copy(update={"result_webhook": None}).model_dump()
    await session.commit()


@router.post("/employees/{employee_id}/webhook/test")
async def test_webhook(
    employee_id: uuid.UUID, request: Request, user: CurrentUser, session: Session
) -> dict[str, Any]:
    """Send an example result to the draft's address now and say what the receiver answered."""
    employee = await load(session, user, employee_id)
    hook = service.bundle_of(employee).result_webhook
    if hook is None:
        raise HTTPException(409, "set the result webhook first")
    await take(session, user, "webhook.test", TESTS_PER_HOUR)
    factory = async_sessionmaker(request.app.state.db, expire_on_commit=False)
    now = datetime.now(UTC)
    test = await delivery.send_test(
        session, user.account_id, events.CALL_COMPLETED, now, hook=(employee.id, hook)
    )
    return await delivery.run_test(factory, test, now)
