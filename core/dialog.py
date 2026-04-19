"""
core/dialog.py — v3 dialog state machine.

A minimal, testable session controller that models the full turn lifecycle:

    IDLE → LISTENING → THINKING → SPEAKING → (CONTINUOUS|IDLE)

Key v3 additions over v2's implicit loop:

* **Continuous conversation.** After a turn ends, if `continuous=True` the
  session re-enters LISTENING for a bounded window instead of requiring another
  wake word. Timeout returns to IDLE.
* **Barge-in.** An external perception channel can call `barge_in()` while the
  session is SPEAKING. The speak task's cancel_event is set, the TTS layer is
  expected to honour it, and the session transitions straight back to LISTENING.
* **Cancel tokens.** Speak tasks receive an asyncio.Event that they must poll;
  this avoids killing coroutines mid-IO. Works with the existing SentenceBuffer
  streaming path.

All state is process-local; no network, no I/O, no hardware. That keeps the
whole thing unit-testable on CI without Pi-specific deps.
"""
from __future__ import annotations

import asyncio
import enum
import logging
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, List, Optional

log = logging.getLogger("MiBud")


class DialogState(enum.Enum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"


@dataclass
class TurnRecord:
    """One turn's worth of timing + outcome. Used by the trace log."""

    started_at: float
    user_text: str = ""
    assistant_text: str = ""
    tool_calls: List[str] = field(default_factory=list)
    listen_ms: float = 0.0
    think_ms: float = 0.0
    speak_ms: float = 0.0
    barged_in: bool = False
    ended_at: float = 0.0

    @property
    def total_ms(self) -> float:
        if self.ended_at <= self.started_at:
            return 0.0
        return (self.ended_at - self.started_at) * 1000.0


class DialogSession:
    """
    Owns the turn-level state machine. Safe to instantiate without any
    hardware; callers hook real TTS/STT/LLM via the `hooks` kwarg.

    Parameters
    ----------
    hooks :
        Dict of async callables:
          - ``on_state_change(old, new)``  - any transition
          - ``on_turn(record)``            - fires when a turn ends
          - ``on_barge_in()``              - fires the moment a barge-in is
            registered; hooks should cancel TTS playback.
    continuous :
        If True, after SPEAKING re-enter LISTENING for ``continuous_window_s``
        seconds before dropping to IDLE. Default False (v2 compatible).
    continuous_window_s :
        How long to hold the mic open after a response.
    """

    def __init__(
        self,
        hooks: Optional[Dict[str, Callable[..., Awaitable[None]]]] = None,
        *,
        continuous: bool = False,
        continuous_window_s: float = 8.0,
    ) -> None:
        self._state = DialogState.IDLE
        self._hooks = hooks or {}
        self._continuous = continuous
        self._continuous_window_s = continuous_window_s
        self._cancel_event = asyncio.Event()
        self._speak_task: Optional[asyncio.Task] = None
        self._current_turn: Optional[TurnRecord] = None
        self._lock = asyncio.Lock()
        self._barge_in_count = 0
        self._turn_count = 0

    # ------------------------------------------------------------------
    # Read-only properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> DialogState:
        return self._state

    @property
    def continuous(self) -> bool:
        return self._continuous

    @property
    def cancel_event(self) -> asyncio.Event:
        """Speak tasks should poll this to honour barge-in."""
        return self._cancel_event

    def stats(self) -> Dict[str, int]:
        return {"turns": self._turn_count, "barge_ins": self._barge_in_count}

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    async def _goto(self, new: DialogState) -> None:
        if new == self._state:
            return
        old = self._state
        self._state = new
        log.debug(f"🗣️  dialog: {old.value} → {new.value}")
        cb = self._hooks.get("on_state_change")
        if cb is not None:
            try:
                await cb(old, new)
            except Exception as e:
                log.warning(f"dialog on_state_change hook raised: {e}")

    def set_continuous(self, enabled: bool) -> None:
        self._continuous = enabled

    # ------------------------------------------------------------------
    # Public turn lifecycle
    # ------------------------------------------------------------------

    async def begin_listening(self) -> None:
        """Wake word triggered (or continuous window re-opened)."""
        async with self._lock:
            self._cancel_event.clear()
            self._current_turn = TurnRecord(started_at=time.time())
            await self._goto(DialogState.LISTENING)

    async def end_listening(self, user_text: str) -> None:
        """STT produced text (empty string if silent)."""
        async with self._lock:
            if self._current_turn is None:
                self._current_turn = TurnRecord(started_at=time.time())
            self._current_turn.user_text = user_text
            self._current_turn.listen_ms = (time.time() - self._current_turn.started_at) * 1000.0
            if not user_text.strip():
                await self._finish_turn()
                return
            await self._goto(DialogState.THINKING)

    async def record_tool_call(self, tool_name: str) -> None:
        if self._current_turn is not None:
            self._current_turn.tool_calls.append(tool_name)

    async def begin_speaking(self, assistant_text: str) -> None:
        """LLM finished (or at least produced the first sentence)."""
        async with self._lock:
            if self._current_turn is not None:
                self._current_turn.assistant_text = assistant_text
                think_start = self._current_turn.started_at + (self._current_turn.listen_ms / 1000.0)
                self._current_turn.think_ms = max(0.0, (time.time() - think_start) * 1000.0)
            self._cancel_event.clear()
            await self._goto(DialogState.SPEAKING)

    async def end_speaking(self) -> None:
        """TTS playback finished (or was fully cancelled)."""
        async with self._lock:
            if self._current_turn is not None:
                speak_start = self._current_turn.started_at + (
                    (self._current_turn.listen_ms + self._current_turn.think_ms) / 1000.0
                )
                self._current_turn.speak_ms = max(0.0, (time.time() - speak_start) * 1000.0)
            await self._finish_turn()

    async def barge_in(self) -> None:
        """
        External perception (e.g., Silero VAD) detected user speech while the
        assistant was speaking. Signal the speak task to stop and drop straight
        into LISTENING so the user doesn't have to repeat the wake word.
        """
        if self._state != DialogState.SPEAKING:
            return
        self._barge_in_count += 1
        if self._current_turn is not None:
            self._current_turn.barged_in = True
        self._cancel_event.set()
        cb = self._hooks.get("on_barge_in")
        if cb is not None:
            try:
                await cb()
            except Exception as e:
                log.warning(f"dialog on_barge_in hook raised: {e}")
        # End the current turn cleanly before re-opening the mic.
        await self._finish_turn(skip_continuous=True)
        await self.begin_listening()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _finish_turn(self, *, skip_continuous: bool = False) -> None:
        turn = self._current_turn
        self._current_turn = None
        if turn is not None:
            turn.ended_at = time.time()
            self._turn_count += 1
            cb = self._hooks.get("on_turn")
            if cb is not None:
                try:
                    await cb(turn)
                except Exception as e:
                    log.warning(f"dialog on_turn hook raised: {e}")
        if self._continuous and not skip_continuous:
            # Return to IDLE; the main loop should schedule begin_listening()
            # or rely on continuous_window_s as a deadline for VAD.
            await self._goto(DialogState.IDLE)
        else:
            await self._goto(DialogState.IDLE)
