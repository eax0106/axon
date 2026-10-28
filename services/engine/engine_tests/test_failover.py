"""Mid-call failover through the real engine app, Vobiz stream, VAD and transport. The failing
vendors are the real Pipecat services (Smallest speech-to-text, Sarvam's LLM, Cartesia's voice)
pointed at local servers that refuse their key or never answer; the vendors they fail over to are
a real Sarvam LLM on a local server and stand-ins for speech."""

import time
from collections.abc import Callable
from typing import Any

import pytest

import engine.services
from app.providers.base import ProviderKind

from .test_call import events
from .vendors import Servers, Speaker, call, switches, vendors, wire

__all__ = ["events", "vendors", "wire"]


def test_refused_vendors_hand_every_leg_to_the_next_one_during_the_call(
    wire: Callable[..., dict[str, str]], events: list[dict[str, Any]]
) -> None:
    urls = wire()
    sent = call(events)

    assert switches(events) == {
        "stt": ("badstt", "goodstt"),
        "llm": ("badllm", "goodllm"),
        "tts": ("badtts", "goodtts"),
    }
    # The caller's turn went to the refused LLM first and was lost; the backup answered it.
    assert Servers.hits(urls["badllm"]) == 1 and Servers.hits(urls["goodllm"]) == 1
    assert "".join(Speaker.said) == "Hello there."
    assert any(m["event"] == "playAudio" for m in sent)  # the caller heard the answer
    assert events[-1] == {"type": "ended", "reason": "max_length"}  # the call stayed up


def test_an_llm_that_never_answers_times_out_and_the_backup_answers(
    wire: Callable[..., dict[str, str]],
    events: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine.services, "LLM_TIMEOUT_S", 1.0)
    urls = wire(llm="hang")
    started = time.monotonic()
    call(events)

    assert switches(events)["llm"] == ("badllm", "goodllm")
    assert Servers.hits(urls["badllm"]) == 1  # no silent retry against the stalled vendor
    assert "".join(Speaker.said) == "Hello there."
    assert time.monotonic() - started < 15


def test_usage_is_metered_per_vendor(
    wire: Callable[..., dict[str, str]], events: list[dict[str, Any]]
) -> None:
    wire()
    call(events)
    usage = next(e for e in events if e["type"] == "usage")
    meters = {(m["kind"], m["vendor"], m["unit"]): m["amount"] for m in usage["meters"]}
    assert meters[("llm", "goodllm", "input_tokens")] == 12
    assert meters[("llm", "goodllm", "output_tokens")] == 3
    assert meters[("stt", "goodstt", "audio_seconds")] > 0
    assert not any(vendor == "badllm" for _, vendor, _ in meters)  # it produced nothing
    assert usage["llm_prompt_tokens"] == 12  # the totals stay as they were


def test_a_tool_failure_is_not_the_vendors_and_does_not_fail_over() -> None:
    import asyncio

    from pipecat.frames.frames import ErrorFrame
    from pipecat.utils.errors import ErrorCategory

    from engine.legs import ServiceLeg

    first, second = Speaker(), Speaker()
    leg = ServiceLeg(ProviderKind.TTS, [("a", first), ("b", second)])
    tool_error = ErrorFrame("tool failed", processor=first, category=ErrorCategory.APPLICATION)
    assert asyncio.run(leg.strategy.handle_error(tool_error)) is None
    assert leg.vendor == "a" and first.is_usable
    vendor_error = ErrorFrame("timeout", processor=first, category=ErrorCategory.CONNECTIVITY)
    assert asyncio.run(leg.strategy.handle_error(vendor_error)) is second
    assert leg.vendor == "b" and not first.is_usable
