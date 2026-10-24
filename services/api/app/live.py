"""Live call events for the dashboard, relayed from the engine's Redis channel."""

import asyncio
import contextlib
import json
import uuid

from fastapi import APIRouter, HTTPException, WebSocket
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth import AuthNotConfiguredError, user_from_token
from app.models import Call

router = APIRouter()
POLL_S = 1.0


def channel(call_id: str) -> str:
    """Redis channel the engine publishes a call's events on (see engine/events.py)."""
    return f"call:{call_id}:events"


@router.websocket("/calls/{call_id}/live")
async def live_call(websocket: WebSocket, call_id: uuid.UUID, token: str = "") -> None:
    """Browsers can't set headers on a WebSocket, so the access token comes as `?token=`.

    Closes with 4401 for a bad token and 4404 for a call outside the user's account; otherwise
    forwards every event until the call's `ended` event or the client goes away.
    """
    # Accept first: a close before accept becomes a plain HTTP 403 and the browser never sees
    # the 4401 / 4404 code.
    await websocket.accept()
    async with async_sessionmaker(websocket.app.state.db)() as session:
        try:
            user = await user_from_token(session, token)
        except (HTTPException, AuthNotConfiguredError):
            await websocket.close(code=4401)
            return
        call = await session.get(Call, call_id)
    if call is None or call.account_id != user.account_id:
        await websocket.close(code=4404)
        return

    async with websocket.app.state.redis.pubsub() as pubsub:
        await pubsub.subscribe(channel(str(call_id)))

        async def forward() -> None:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=POLL_S)
                if message:
                    data = message["data"].decode()
                    await websocket.send_text(data)
                    if json.loads(data).get("type") == "ended":
                        return

        async def client_gone() -> None:
            with contextlib.suppress(Exception):
                while True:
                    await websocket.receive_text()

        tasks = [asyncio.create_task(forward()), asyncio.create_task(client_gone())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            task.result()
    with contextlib.suppress(Exception):
        await websocket.close()
