"""The three AI legs of a call (speech-to-text, LLM, text-to-speech), each a switcher over every
vendor that can serve it, in the order to try them (`app.providers.failover.chain`, unhealthy
vendors last). When the active vendor fails the call moves to the next one; see `WriteOffFailover`.
"""

import time
from typing import Any

from pipecat.frames.frames import ErrorFrame
from pipecat.pipeline.service_switcher import ServiceSwitcher, ServiceSwitcherStrategyFailover
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.utils.errors import ErrorCategory

from app.models import Voice, VoiceTier
from app.providers.base import Provider, ProviderKind, ProviderNotConfiguredError
from app.providers.failover import TTS_TIER, chain, ordered
from app.providers.registry import resolve
from engine.services import SERVICES, Delivery

STRIKES = 3  # errors the last vendor of a leg may make within STRIKE_WINDOW_S before it is given up
STRIKE_WINDOW_S = 30.0


class WriteOffFailover(ServiceSwitcherStrategyFailover):
    """Leave a vendor at its first real error while another one is left: a caller cannot wait
    for a vendor to recover, and Pipecat calls most outages (a refused connection, a timeout)
    transient. The last vendor of a leg is given up after STRIKES errors in STRIKE_WINDOW_S, or at
    once when the error is permanent (rejected key). Errors from our own code (`APPLICATION`, such
    as a tool handler) say nothing about the vendor and are ignored.

    Events: `on_failover(strategy, failed, replacement, error)` and, once, `on_exhausted(strategy,
    failed, error)` when the leg has nothing left."""

    def __init__(self, services: list[FrameProcessor]) -> None:
        super().__init__(services)
        self._register_event_handler("on_failover")
        self._register_event_handler("on_exhausted")
        self._strikes: list[float] = []
        self.exhausted = False

    async def handle_error(self, error: ErrorFrame) -> FrameProcessor | None:
        if error.category is ErrorCategory.APPLICATION or self.exhausted:
            return None
        failed = error.processor or self._active_service
        at = self._services.index(self._active_service)
        backup = next(
            (s for s in self._services[at + 1 :] + self._services[:at] if s.is_usable), None
        )
        if backup is not None:
            await failed.set_usable(False)
            switched = await self._set_active_if_available(backup)
            await self._call_event_handler("on_failover", failed, backup, error.error)
            return switched
        now = time.monotonic()
        self._strikes = [t for t in self._strikes if now - t < STRIKE_WINDOW_S] + [now]
        if failed.is_usable and len(self._strikes) < STRIKES:
            return None
        self.exhausted = True
        await failed.set_usable(False)
        await self._call_event_handler("on_exhausted", failed, error.error)
        return None


class _Leg:
    """What a switcher needs to say about the vendors it holds."""

    kind: ProviderKind
    vendors: dict[FrameProcessor, str]
    tiers: dict[FrameProcessor, VoiceTier | None]
    strategy: Any

    def _hold(self, kind: ProviderKind, candidates: list[tuple[str, FrameProcessor]]) -> None:
        self.kind = kind
        self.vendors = {service: vendor for vendor, service in candidates}
        self.tiers = {
            s: TTS_TIER.get(v) if kind is ProviderKind.TTS else None for v, s in candidates
        }

    @property
    def vendor(self) -> str:
        return self.vendors[self.strategy.active_service]


class ServiceLeg(ServiceSwitcher[WriteOffFailover], _Leg):
    def __init__(self, kind: ProviderKind, candidates: list[tuple[str, FrameProcessor]]) -> None:
        super().__init__([s for _, s in candidates], WriteOffFailover)
        self._hold(kind, candidates)


class LLMLeg(ServiceLeg):
    """The LLM leg: functions are registered on every vendor, so a backup can use them too."""

    def __init__(self, candidates: list[tuple[str, FrameProcessor]]) -> None:
        super().__init__(ProviderKind.LLM, candidates)

    def register_function(self, name: str, handler: Any, **options: Any) -> None:
        for service in self.services:
            register = getattr(service, "register_function", None)
            if register is not None:
                register(name, handler, **options)


def _service(provider: Provider, language: str, delivery: Delivery) -> FrameProcessor:
    factory = SERVICES.get((provider.kind, provider.name))
    if factory is None:
        detail = f"{provider.kind} adapter {provider.name!r} has no pipeline service"
        raise ProviderNotConfiguredError(provider.kind, provider.name, [], detail)
    return factory(language, delivery)


def _candidates(
    kind: ProviderKind,
    vendors: list[str],
    language: str,
    delivery: Delivery,
    own: tuple[str, Delivery] | None = None,
) -> list[tuple[str, FrameProcessor]]:
    """A built service per vendor that can be built. A vendor that cannot (a missing key, a voice
    it lacks for this language) is left out, like an unhealthy one; with none left, the first
    vendor's error is raised (served as 503 naming what is missing). `own` is the employee's
    chosen vendor with its own voice."""
    built: list[tuple[str, FrameProcessor]] = []
    first: ProviderNotConfiguredError | None = None
    for vendor in vendors:
        chosen = delivery if own is None or own[0] != vendor else own[1]
        try:
            built.append((vendor, _service(resolve(kind, vendor), language, chosen)))
        except ProviderNotConfiguredError as exc:
            first = first or exc
    if not built:
        assert first is not None  # a chain always names at least one vendor
        raise first
    return built


def voice_legs(
    language: str,
    tier: VoiceTier | None = None,
    voice: Voice | None = None,
    speed: float = 1.0,
    down: frozenset[tuple[str, str]] = frozenset(),
) -> tuple[ServiceLeg, LLMLeg, ServiceLeg]:
    """STT, LLM and TTS legs for a call, or ProviderNotConfiguredError (served as 503).

    A `voice` row (from the voices table) decides the first TTS vendor, the voice id and the
    tier. Otherwise `tier` picks the vendor; without either the selected TTS vendor leads with its
    default voice. Fallback voices are each vendor's default voice for the language, at the same
    speed. `down` holds the (kind, vendor) pairs that are unhealthy right now: tried last."""
    plain = Delivery(speed=speed)
    tier = voice.tier if voice is not None else tier
    own = (voice.provider, Delivery(voice.provider_voice_id, speed)) if voice else None

    def legs(kind: ProviderKind) -> list[tuple[str, FrameProcessor]]:
        vendors = chain(kind, tier, own[0] if own and kind is ProviderKind.TTS else None)
        mine = own if kind is ProviderKind.TTS else None
        return _candidates(kind, ordered(kind, vendors, down), language, plain, mine)

    return (
        ServiceLeg(ProviderKind.STT, legs(ProviderKind.STT)),
        LLMLeg(legs(ProviderKind.LLM)),
        ServiceLeg(ProviderKind.TTS, legs(ProviderKind.TTS)),
    )
