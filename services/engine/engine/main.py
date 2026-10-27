"""Voice engine HTTP + WebSocket app (run: uvicorn engine.main:app).

Vobiz flow: the call is answered -> Vobiz POSTs our answer URL -> we return XML with a <Stream>
pointing at /vobiz/stream -> Vobiz opens that WebSocket and sends `start` then `media`.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlencode

from fastapi import FastAPI, Request, Response, WebSocket
from loguru import logger
from pipecat.processors.frame_processor import FrameProcessor
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.websockets import WebSocketState

from app.employees.tickets import issue_call_ticket, read_call_ticket
from app.employees.tickets import read as read_ticket
from app.inbound import transfer as transferring
from app.inbound.routing import route
from app.main import provider_not_configured
from app.providers.base import ProviderKind, ProviderNotConfiguredError, TelephonyProvider
from app.providers.registry import require
from app.settings import engine_public_url, get_settings
from engine.call import CallSettings, run_call
from engine.events import redis_sink
from engine.legs import voice_legs
from engine.plan import claim_test_call, load_plan
from engine.records import CallRecorder
from engine.vobiz import (
    HANGUP_XML,
    REJECT_XML,
    StreamStart,
    VobizFrameSerializer,
    answer_xml,
    transfer_xml,
)
from engine.web import WebFrameSerializer

START_TIMEOUT_S = 10.0  # Vobiz sends `start` right after connecting
TRANSFER_TICKET_TTL = timedelta(minutes=2)  # the carrier fetches the transfer XML at once
RESULT_TICKET_TTL = timedelta(seconds=transferring.DIAL_LIMIT_S + 3600)  # it answers after the talk
SUPPORTED_LANGUAGES = {"te", "hi", "en"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.redis = Redis.from_url(settings.redis_url)
    app.state.db = create_async_engine(settings.database_url, pool_pre_ping=True)
    yield
    await app.state.db.dispose()
    await app.state.redis.aclose()


app = FastAPI(title="Axon Voice Engine", lifespan=lifespan)
app.exception_handler(ProviderNotConfiguredError)(provider_not_configured)


def _telephony() -> TelephonyProvider:
    provider = require(ProviderKind.TELEPHONY)
    assert isinstance(provider, TelephonyProvider)
    return provider


def _language(lang: str) -> str:
    return lang if lang in SUPPORTED_LANGUAGES else "en"


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


def _recorder(app_: FastAPI, call: str) -> CallRecorder | None:
    """The recorder for our own `calls` row, when the answer URL named one."""
    try:
        return CallRecorder(app_.state.db, uuid.UUID(call))
    except ValueError:
        return None


class _NoPlanError(Exception):
    """The employee is unknown, or has nothing published and this is not a test call."""


async def _setup(
    app_: FastAPI, lang: str, employee: str, call: str
) -> tuple[tuple[FrameProcessor, FrameProcessor, FrameProcessor], CallSettings]:
    """The legs and settings for a call: the employee's own when `employee` is given, else the
    defaults. Raises ProviderNotConfiguredError (503) or _NoPlanError."""
    if not employee:
        language = _language(lang)
        return voice_legs(language), CallSettings(language=language)
    plan = await load_plan(app_.state.db, employee, call)
    if plan is None:
        raise _NoPlanError
    legs = voice_legs(plan.language, voice=plan.voice, speed=plan.tts_speed)
    return legs, CallSettings(
        language=plan.language,
        system_prompt=plan.system_prompt,
        voice_tier=plan.voice.tier.value if plan.voice else None,
        ambience=plan.ambience,
        ambience_volume=plan.ambience_volume,
        opening=plan.opening,
        transfer_to=plan.transfer_to,
    )


@app.post("/vobiz/answer")
async def vobiz_answer(
    request: Request, lang: str = "en", call: str = "", employee: str = ""
) -> Response:
    """Answer URL for Vobiz calls. 503 provider_not_configured until every leg can run.

    `call` is our calls.id when the dialer (B5) or inbound routing (B9) created the row; live
    events are published under it, else under the carrier's call id. `employee` selects whose
    script, voice and settings the call runs on.
    """
    try:
        _, settings = await _setup(request.app, lang, employee, call)
    except _NoPlanError:
        return Response("employee not found or not published", status_code=404)
    _telephony()
    return _stream_response(settings.language, call, employee)


def _stream_response(language: str, call: str, employee: str) -> Response:
    stream_url = "wss://" + engine_public_url().removeprefix("https://") + "/vobiz/stream"
    query = {"lang": language, "call": call}
    if employee:
        query["employee"] = employee
    return Response(answer_xml(f"{stream_url}?{urlencode(query)}"), media_type="application/xml")


def _xml(body: str) -> Response:
    return Response(body, media_type="application/xml")


@app.post("/vobiz/inbound")
async def vobiz_inbound(request: Request) -> Response:
    """Answer URL of the voice application our numbers are routed to: a call has arrived. The call
    is answered when the employee can take it, and turned away (rejected) otherwise; either way
    it is recorded."""
    telephony = _telephony()
    engine_public_url()  # 503 now, rather than an answer the carrier cannot follow
    form = parse_qs((await request.body()).decode("utf-8", "replace"))

    def field(name: str) -> str:
        return (form.get(name) or [""])[0]

    factory = async_sessionmaker(request.app.state.db, expire_on_commit=False)
    routed = await route(
        factory,
        telephony,
        to=field("To"),
        caller=field("From"),
        carrier_id=field("CallUUID"),
        now=datetime.now(UTC),
    )
    if routed.kind != "answer":
        return _xml(REJECT_XML)
    return _stream_response(
        _language(routed.language), str(routed.call_id), str(routed.employee_id)
    )


@app.api_route("/vobiz/transfer", methods=["GET", "POST"])
async def vobiz_transfer(request: Request, ticket: str = "") -> Response:
    """The instructions the carrier runs on the caller's leg when the AI hands the call to a
    person: ring the number the owner chose, and report back. Opened only by a ticket the engine
    gave out for this one call."""
    call_id = read_call_ticket(ticket, "transfer")
    if call_id is None:
        return Response("invalid or expired ticket", status_code=403)
    factory = async_sessionmaker(request.app.state.db, expire_on_commit=False)
    async with factory() as session:
        found = await transferring.target(session, call_id)
    if found is None:
        return _xml(HANGUP_XML)
    person, caller_id = found
    result = issue_call_ticket("transfer_result", call_id, RESULT_TICKET_TTL)
    result_url = f"{engine_public_url()}/vobiz/transfer-result?{urlencode({'ticket': result})}"
    return _xml(
        transfer_xml(
            person,
            caller_id,
            result_url,
            timeout=transferring.DIAL_TIMEOUT_S,
            limit=transferring.DIAL_LIMIT_S,
        )
    )


@app.post("/vobiz/transfer-result")
async def vobiz_transfer_result(request: Request, ticket: str = "") -> Response:
    """How the transfer ended. The call is over for the caller either way."""
    call_id = read_call_ticket(ticket, "transfer_result")
    if call_id is None:
        return Response("invalid or expired ticket", status_code=403)
    form = parse_qs((await request.body()).decode("utf-8", "replace"))
    dial_status = (form.get("DialStatus") or ["unknown"])[0][:30]
    factory = async_sessionmaker(request.app.state.db, expire_on_commit=False)
    async with factory() as session:
        await transferring.record_result(session, call_id, dial_status, datetime.now(UTC))
        await session.commit()
    return _xml(HANGUP_XML)


async def _read_start(websocket: WebSocket) -> StreamStart:
    while True:
        message = json.loads(await websocket.receive_text())
        if message.get("event") == "start":
            return StreamStart.parse(message)


@app.websocket("/vobiz/stream")
async def vobiz_stream(
    websocket: WebSocket, lang: str = "en", call: str = "", employee: str = ""
) -> None:
    await websocket.accept()
    try:
        legs, settings = await _setup(websocket.app, lang, employee, call)
        telephony = _telephony()
    except ProviderNotConfiguredError as exc:
        await websocket.close(code=1011, reason=f"provider_not_configured: {exc.detail}"[:120])
        return
    except _NoPlanError:
        await websocket.close(code=1008, reason="employee not found or not published")
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
    serializer = VobizFrameSerializer(start, hang_up=hang_up)
    recorder = _recorder(websocket.app, call)
    transfer = None
    if settings.transfer_to and recorder is not None:  # a ticket needs our call row to name

        async def transfer() -> None:
            ticket = issue_call_ticket("transfer", recorder.call_id, TRANSFER_TICKET_TTL)
            url = f"{engine_public_url()}/vobiz/transfer?{urlencode({'ticket': ticket})}"
            await telephony.transfer(start.call_id, url)

    await run_call(
        websocket,
        start.call_id,
        serializer,
        legs,
        settings,
        publish,
        recorder,
        carrier_call_id=start.call_id,
        transfer=transfer,
    )


@app.websocket("/web/stream")
async def web_stream(websocket: WebSocket, ticket: str = "") -> None:
    """Browser test call. The ticket comes from the API (POST /employees/{id}/web-test-call)."""
    await websocket.accept()
    granted = read_ticket(ticket)
    if granted is None:
        await websocket.close(code=1008, reason="invalid or expired ticket")
        return
    if not await claim_test_call(websocket.app.state.db, granted.call_id, granted.account_id):
        await websocket.close(code=1008, reason="ticket already used")
        return
    # The ticket is spent and the call is in progress: whatever goes wrong now must close the row.
    recorder = CallRecorder(websocket.app.state.db, granted.call_id)
    try:
        legs, settings = await _setup(
            websocket.app, "en", str(granted.employee_id), str(granted.call_id)
        )
    except ProviderNotConfiguredError as exc:
        await recorder.abandon("provider_not_configured")
        await websocket.close(code=1011, reason=f"provider_not_configured: {exc.detail}"[:120])
        return
    except _NoPlanError:
        await recorder.abandon("employee_not_found")
        await websocket.close(code=1008, reason="employee not found")
        return
    publish = redis_sink(websocket.app.state.redis, str(granted.call_id))
    try:
        await run_call(
            websocket, str(granted.call_id), WebFrameSerializer(), legs, settings, publish, recorder
        )
    finally:
        if websocket.client_state != WebSocketState.DISCONNECTED:
            await websocket.close()
