"""Tests for core.dialog — DialogSession state machine."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.dialog import DialogSession, DialogState, TurnRecord


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if asyncio.get_event_loop().is_running() is False else asyncio.run(coro)


def test_initial_state_is_idle():
    s = DialogSession()
    assert s.state is DialogState.IDLE
    assert s.continuous is False
    assert s.stats() == {"turns": 0, "barge_ins": 0}


def test_full_turn_lifecycle_idle_listen_think_speak_idle():
    s = DialogSession()
    captured: list[TurnRecord] = []

    async def on_turn(r):
        captured.append(r)

    s._hooks = {"on_turn": on_turn}

    async def run():
        await s.begin_listening()
        assert s.state is DialogState.LISTENING
        await s.end_listening("what's the time?")
        assert s.state is DialogState.THINKING
        await s.begin_speaking("it's 3pm")
        assert s.state is DialogState.SPEAKING
        await s.end_speaking()
        assert s.state is DialogState.IDLE

    asyncio.run(run())
    assert len(captured) == 1
    turn = captured[0]
    assert turn.user_text == "what's the time?"
    assert turn.assistant_text == "it's 3pm"
    assert turn.barged_in is False
    assert turn.total_ms >= 0.0
    assert s.stats()["turns"] == 1


def test_empty_user_text_skips_think_speak_and_finishes_turn():
    s = DialogSession()
    captured: list[TurnRecord] = []

    async def on_turn(r):
        captured.append(r)

    s._hooks = {"on_turn": on_turn}

    async def run():
        await s.begin_listening()
        await s.end_listening("")
        # Should have returned to IDLE directly.
        assert s.state is DialogState.IDLE

    asyncio.run(run())
    assert len(captured) == 1
    assert captured[0].user_text == ""
    assert captured[0].assistant_text == ""


def test_barge_in_sets_cancel_event_and_reopens_listening():
    s = DialogSession()
    fired: list[bool] = []

    async def on_barge_in():
        fired.append(True)

    s._hooks = {"on_barge_in": on_barge_in}

    async def run():
        await s.begin_listening()
        await s.end_listening("tell me a long story")
        await s.begin_speaking("once upon a time, a hero set out…")
        assert s.state is DialogState.SPEAKING
        assert not s.cancel_event.is_set()
        await s.barge_in()
        # barge-in should fire the hook, set cancel event, then re-open mic.
        assert fired == [True]
        assert s.state is DialogState.LISTENING

    asyncio.run(run())
    assert s.stats()["barge_ins"] == 1
    # cancel_event is cleared on re-entry to LISTENING so new speak task starts clean
    assert not s.cancel_event.is_set()


def test_barge_in_outside_speaking_is_noop():
    s = DialogSession()

    async def run():
        await s.barge_in()
        assert s.state is DialogState.IDLE
        await s.begin_listening()
        await s.barge_in()
        assert s.state is DialogState.LISTENING

    asyncio.run(run())
    assert s.stats()["barge_ins"] == 0


def test_state_change_hook_receives_old_and_new():
    s = DialogSession()
    transitions: list[tuple[DialogState, DialogState]] = []

    async def on_change(old, new):
        transitions.append((old, new))

    s._hooks = {"on_state_change": on_change}

    async def run():
        await s.begin_listening()
        await s.end_listening("hi")
        await s.begin_speaking("hello!")
        await s.end_speaking()

    asyncio.run(run())
    # Sequence: IDLE->LISTENING, LISTENING->THINKING, THINKING->SPEAKING, SPEAKING->IDLE
    assert [(o.value, n.value) for o, n in transitions] == [
        ("idle", "listening"),
        ("listening", "thinking"),
        ("thinking", "speaking"),
        ("speaking", "idle"),
    ]


def test_record_tool_call_attaches_to_current_turn():
    s = DialogSession()
    captured: list[TurnRecord] = []

    async def on_turn(r):
        captured.append(r)

    s._hooks = {"on_turn": on_turn}

    async def run():
        await s.begin_listening()
        await s.end_listening("set a timer for 5 minutes")
        await s.record_tool_call("set_timer")
        await s.record_tool_call("get_time")
        await s.begin_speaking("timer set")
        await s.end_speaking()

    asyncio.run(run())
    assert captured[0].tool_calls == ["set_timer", "get_time"]


def test_continuous_mode_flag_toggles():
    s = DialogSession(continuous=False)
    assert s.continuous is False
    s.set_continuous(True)
    assert s.continuous is True


def test_hook_exceptions_are_caught():
    s = DialogSession()

    async def boom(*a, **kw):
        raise RuntimeError("hook failed")

    s._hooks = {"on_state_change": boom, "on_turn": boom, "on_barge_in": boom}

    async def run():
        # Should not raise despite every hook blowing up.
        await s.begin_listening()
        await s.end_listening("hi")
        await s.begin_speaking("hi!")
        await s.barge_in()  # triggers on_barge_in and finish_turn
        await s.end_speaking()

    asyncio.run(run())
    # State should still be coherent.
    assert s.state in {DialogState.IDLE, DialogState.LISTENING}
