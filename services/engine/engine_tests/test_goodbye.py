"""The AI's end-of-call hang-up waits for the goodbye to finish playing at the carrier."""

import asyncio
from typing import Any

from pipecat.frames.frames import InputTransportMessageFrame, TTSStartedFrame, TTSStoppedFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.google.llm import GoogleLLMService

from engine.call import END_CALL, UtteranceCheckpoints, register_end_call
from engine.goodbye import GoodbyeGate, PlayedStreamTap


def gate(ended: list[str], **times: float) -> GoodbyeGate:
    async def end(reason: str) -> None:
        ended.append(reason)

    return GoodbyeGate(
        end, settle_s=times.get("settle_s", 0.02), timeout_s=times.get("timeout_s", 1.0)
    )


async def settle() -> None:
    await asyncio.sleep(0.1)


def test_idle_gate_ends_after_the_settle_time() -> None:
    async def run() -> list[str]:
        ended: list[str] = []
        g = gate(ended)
        await g.request_end()
        await settle()
        return ended

    assert asyncio.run(run()) == ["agent_ended"]


def test_it_waits_for_the_last_utterance_to_be_played() -> None:
    async def run() -> tuple[list[str], list[str]]:
        ended: list[str] = []
        g = gate(ended)
        g.tts_started()
        g.checkpoint_issued("utt-1")
        g.tts_stopped()
        await g.request_end()
        await settle()
        while_unplayed = list(ended)
        g.played_stream("utt-1")
        await settle()
        return while_unplayed, ended

    waiting, done = asyncio.run(run())
    assert waiting == [] and done == ["agent_ended"]


def test_it_waits_while_the_bot_is_still_speaking() -> None:
    async def run() -> tuple[list[str], list[str]]:
        ended: list[str] = []
        g = gate(ended)
        g.tts_started()
        await g.request_end()
        await settle()
        while_speaking = list(ended)
        g.checkpoint_issued("utt-1")
        g.tts_stopped()
        g.played_stream("utt-1")
        await settle()
        return while_speaking, ended

    speaking, done = asyncio.run(run())
    assert speaking == [] and done == ["agent_ended"]


def test_it_hangs_up_anyway_after_the_timeout_when_playback_is_never_confirmed() -> None:
    async def run() -> list[str]:
        ended: list[str] = []
        g = gate(ended, timeout_s=0.15)
        g.checkpoint_issued("utt-1")
        await g.request_end()
        await asyncio.sleep(0.4)
        return ended

    assert asyncio.run(run()) == ["agent_ended"]


def test_asking_twice_ends_once_and_cancel_stops_a_pending_end() -> None:
    async def run() -> tuple[list[str], list[str]]:
        ended: list[str] = []
        g = gate(ended)
        await g.request_end()
        await g.request_end()
        await settle()
        cancelled: list[str] = []
        c = gate(cancelled)
        c.checkpoint_issued("utt-1")
        await c.request_end()
        c.cancel()
        await settle()
        return ended, cancelled

    ended, cancelled = asyncio.run(run())
    assert ended == ["agent_ended"] and cancelled == []


def test_played_stream_tap_reports_only_playedstream_messages() -> None:
    async def run() -> set[str]:
        g = gate([])
        tap = PlayedStreamTap(g)
        pushed: list[Any] = []

        async def push(frame: Any, direction: Any = None) -> None:
            pushed.append(frame)

        tap.push_frame = push  # type: ignore[method-assign]
        for message in (
            {"event": "playedStream", "name": "utt-2"},
            {"event": "clearedAudio"},
            {"event": "playedStream", "name": "utt-3"},
        ):
            await tap.process_frame(
                InputTransportMessageFrame(message=message), FrameDirection.DOWNSTREAM
            )
        assert len(pushed) == 3  # everything still flows on
        return g._played

    assert asyncio.run(run()) == {"utt-2", "utt-3"}


def test_utterance_checkpoints_tell_the_gate_what_is_in_flight() -> None:
    async def run() -> tuple[bool, bool, bool]:
        g = gate([])
        stage = UtteranceCheckpoints(g)

        async def push(frame: Any, direction: Any = None) -> None:
            return None

        stage.push_frame = push  # type: ignore[method-assign]
        await stage.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)
        speaking = not g.idle()
        await stage.process_frame(TTSStoppedFrame(), FrameDirection.DOWNSTREAM)
        unplayed = not g.idle()
        g.played_stream("utt-1")
        return speaking, unplayed, g.idle()

    assert asyncio.run(run()) == (True, True, True)


def test_the_end_call_tool_is_registered_on_a_real_llm_service() -> None:
    llm = GoogleLLMService(api_key="test-key")
    register_end_call(llm, gate([]))
    assert "end_call" in llm._functions
    assert END_CALL.name == "end_call" and END_CALL.required == []


def test_calling_the_tool_asks_the_gate_to_end_without_another_llm_turn() -> None:
    async def run() -> tuple[list[str], list[Any]]:
        ended: list[str] = []
        g = gate(ended)
        registered: dict[str, Any] = {}

        class Llm:
            def register_function(self, name: str, handler: Any) -> None:
                registered[name] = handler

        register_end_call(Llm(), g)  # type: ignore[arg-type]
        results: list[Any] = []

        class Params:
            async def result_callback(self, result: Any, properties: Any = None) -> None:
                results.append((result, properties))

        await registered["end_call"](Params())
        await settle()
        return ended, results

    ended, results = asyncio.run(run())
    assert ended == ["agent_ended"]
    assert results[0][0] == {"status": "ending"} and results[0][1].run_llm is False


def test_a_leg_without_function_calling_is_left_alone() -> None:
    register_end_call(object(), gate([]))  # type: ignore[arg-type]
