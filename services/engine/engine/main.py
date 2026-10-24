"""Voice engine HTTP + WebSocket app (run: uvicorn engine.main:app).

Vobiz flow: the call is answered -> Vobiz POSTs our answer URL -> we return XML with a <Stream>
pointing at /vobiz/stream -> Vobiz opens that WebSocket and sends `start` then `media`.
"""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlencode

from fastapi import FastAPI, Response, WebSocket
from loguru import logger
from redis.asyncio import Redis

from app.main import provider_not_configured
from app.providers.base import ProviderKind, TelephonyProvider
from app.providers.registry import ProviderNotConfiguredError, require
from app.settings import get_settings
from engine.call import CallSettings, run_call
from engine.events import redis_sink
from engine.legs import voice_legs
from engine.vobiz import StreamStart, answer_xml

PUBLIC_URL_ENV = "AXON_ENGINE_PUBLIC_URL"
START_TIMEOUT_S = 10.0  # Vobiz sends `start` right after connecting
SUPPORTED_LANGUAGES = {"te", "hi", "en"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.redis = Redis.from_url(get_settings().redis_url)
    yield
    await app.state.redis.aclose()


app = FastAPI(title="Axon Voice Engine", lifespan=lifespan)
app.exception_handler(ProviderNotConfiguredError)(provider_not_configured)


def _telephony() -> TelephonyProvider:
    provider = require(ProviderKind.TELEPHONY)
    assert isinstance(provider, TelephonyProvider)
    return provider


def _public_url() -> str:
    url = os.environ.get(PUBLIC_URL_ENV, "").rstrip("/")
    if not url.startswith("https://"):
        raise ProviderNotConfiguredError(
            ProviderKind.TELEPHONY,
            "vobiz",
            [PUBLIC_URL_ENV],
            f"{PUBLIC_URL_ENV} must be the engine's public https URL (Vobiz must reach it)",
        )
    return url


def _language(lang: str) -> str:
    return lang if lang in SUPPORTED_LANGUAGES else "en"


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/vobiz/answer")
async def vobiz_answer(lang: str = "en", call: str = "") -> Response:
    """Answer URL for Vobiz calls. 503 provider_not_configured until every leg can run.

    `call` is our calls.id when the dialer (B5) or inbound routing (B9) created the row; live
    events are published under it, else under the carrier's call id.
    """
    language = _language(lang)
    voice_legs(language)
    _telephony()
    stream_url = "wss://" + _public_url().removeprefix("https://") + "/vobiz/stream"
    return Response(
        answer_xml(f"{stream_url}?{urlencode({'lang': language, 'call': call})}"),
        media_type="application/xml",
    )


async def _read_start(websocket: WebSocket) -> StreamStart:
    while True:
        message = json.loads(await websocket.receive_text())
        if message.get("event") == "start":
            return StreamStart.parse(message)


@app.websocket("/vobiz/stream")
async def vobiz_stream(websocket: WebSocket, lang: str = "en", call: str = "") -> None:
    await websocket.accept()
    language = _language(lang)
    try:
        legs = voice_legs(language)
        telephony = _telephony()
    except ProviderNotConfiguredError as exc:
        await websocket.close(code=1011, reason=f"provider_not_configured: {exc.detail}"[:120])
        return
    try:
        start = await asyncio.wait_for(_read_start(websocket), START_TIMEOUT_S)
    except (TimeoutError, json.JSONDecodeError, KeyError):
        await websocket.close(code=1008, reason="no valid start message")
        return
    # The stream URL is public, so only serve calls the carrier really has up.
    if not await telephony.is_live(start.call_id):
        logger.warning(f"vobiz stream for unknown call {start.call_id} refused")
        await websocket.close(code=1008, reason="unknown call")
        return

    async def hang_up() -> None:
        # One retry: a call left up after the AI ends it keeps costing the account money.
        for attempt in (1, 2):
            try:
                await telephony.hang_up(start.call_id)
                return
            except Exception:
                logger.exception(f"hang-up of {start.call_id} failed (attempt {attempt} of 2)")

    publish = redis_sink(websocket.app.state.redis, call or start.call_id)
    await run_call(websocket, start, legs, CallSettings(language=language), publish, hang_up)
