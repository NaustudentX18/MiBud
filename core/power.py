"""
MiBud Core - Power Profiles

Auto-shifts MiBud between ECO / BALANCED / PERFORMANCE modes based on battery
level and charging state. Each profile nudges:

- Preferred AI model (offline vs online, small vs large)
- Display brightness + clock refresh
- Wake-word poll interval
- Max response tokens (shorter answers = faster + less audio to synth)
- TTS provider preference
- Whether to prefer offline STT

The profile is applied as a dict of overlays the rest of the app reads via
`get_current_profile()`. Callers can also subscribe to change events.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("MiBud")


class PowerProfile(Enum):
    ECO = "eco"
    BALANCED = "balanced"
    PERFORMANCE = "performance"


@dataclass
class ProfileSettings:
    name: PowerProfile
    display_brightness: int
    display_refresh_seconds: int
    wake_poll_ms: int
    ai_max_tokens: int
    prefer_offline_llm: bool
    prefer_offline_stt: bool
    prefer_offline_tts: bool
    preferred_online_model: Optional[str] = None
    preferred_offline_model: Optional[str] = None


DEFAULTS: Dict[PowerProfile, ProfileSettings] = {
    PowerProfile.ECO: ProfileSettings(
        name=PowerProfile.ECO,
        display_brightness=30,
        display_refresh_seconds=5,
        wake_poll_ms=80,
        ai_max_tokens=180,
        prefer_offline_llm=True,
        prefer_offline_stt=True,
        prefer_offline_tts=True,
        preferred_online_model="google/gemini-2.0-flash-lite:free",
        preferred_offline_model="phi3:latest",
    ),
    PowerProfile.BALANCED: ProfileSettings(
        name=PowerProfile.BALANCED,
        display_brightness=60,
        display_refresh_seconds=2,
        wake_poll_ms=40,
        ai_max_tokens=400,
        prefer_offline_llm=False,
        prefer_offline_stt=False,
        prefer_offline_tts=False,
        preferred_online_model="google/gemini-2.0-flash-lite:free",
        preferred_offline_model="phi3:latest",
    ),
    PowerProfile.PERFORMANCE: ProfileSettings(
        name=PowerProfile.PERFORMANCE,
        display_brightness=90,
        display_refresh_seconds=1,
        wake_poll_ms=20,
        ai_max_tokens=700,
        prefer_offline_llm=False,
        prefer_offline_stt=False,
        prefer_offline_tts=False,
        preferred_online_model=None,   # let the router pick
        preferred_offline_model=None,
    ),
}


@dataclass
class PowerManagerConfig:
    auto: bool = True
    eco_below_percent: int = 25          # switch to ECO if battery under 25%
    performance_on_charge: bool = True   # switch to PERFORMANCE while charging
    manual_profile: PowerProfile = PowerProfile.BALANCED
    profiles: Dict[PowerProfile, ProfileSettings] = field(default_factory=lambda: dict(DEFAULTS))


class PowerManager:
    """Watches battery state and publishes the active profile."""

    def __init__(
        self,
        cfg: PowerManagerConfig,
        *,
        battery: Any = None,
        poll_interval: float = 15.0,
    ) -> None:
        self.cfg = cfg
        self.battery = battery
        self.poll_interval = poll_interval
        self._current: PowerProfile = cfg.manual_profile
        self._listeners: List[Callable[[ProfileSettings], Any]] = []
        self._task: Optional[asyncio.Task] = None
        self._running = False

    # ---- profile access ------------------------------------------------

    def get_current(self) -> ProfileSettings:
        return self.cfg.profiles[self._current]

    def get_current_name(self) -> str:
        return self._current.value

    def set_manual(self, profile: PowerProfile) -> None:
        self.cfg.auto = False
        self.cfg.manual_profile = profile
        self._apply(profile, reason="manual")

    def set_auto(self) -> None:
        self.cfg.auto = True
        self._evaluate()

    # ---- listeners -----------------------------------------------------

    def subscribe(self, fn: Callable[[ProfileSettings], Any]) -> None:
        self._listeners.append(fn)

    def _notify(self) -> None:
        settings = self.get_current()
        for fn in list(self._listeners):
            try:
                result = fn(settings)
                if asyncio.iscoroutine(result):
                    asyncio.create_task(result)
            except Exception as e:
                log.error(f"⚡ power listener failed: {e}")

    # ---- lifecycle -----------------------------------------------------

    async def start(self) -> None:
        if self._task is not None:
            return
        self._running = True
        self._evaluate()  # initial application
        self._task = asyncio.create_task(self._loop(), name="mibud-power")
        log.info(f"⚡ Power manager started (profile={self._current.value})")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        try:
            while self._running:
                try:
                    self._evaluate()
                except Exception as e:  # pragma: no cover
                    log.error(f"⚡ power eval failed: {e}")
                await asyncio.sleep(self.poll_interval)
        except asyncio.CancelledError:
            return

    # ---- logic ---------------------------------------------------------

    def _evaluate(self) -> None:
        if not self.cfg.auto:
            if self._current != self.cfg.manual_profile:
                self._apply(self.cfg.manual_profile, reason="manual")
            return
        target = PowerProfile.BALANCED
        if self.battery is not None:
            try:
                status = self.battery.get_status()
            except Exception:
                status = None
            if status is not None:
                if status.charging and self.cfg.performance_on_charge:
                    target = PowerProfile.PERFORMANCE
                elif int(status.level) <= self.cfg.eco_below_percent:
                    target = PowerProfile.ECO
        self._apply(target, reason="auto")

    def _apply(self, profile: PowerProfile, *, reason: str) -> None:
        if profile == self._current:
            return
        old = self._current
        self._current = profile
        log.info(f"⚡ Power profile {old.value} -> {profile.value} ({reason})")
        self._notify()

    # ---- snapshot ------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        s = self.get_current()
        return {
            "profile": s.name.value,
            "auto": self.cfg.auto,
            "display_brightness": s.display_brightness,
            "wake_poll_ms": s.wake_poll_ms,
            "ai_max_tokens": s.ai_max_tokens,
            "prefer_offline_llm": s.prefer_offline_llm,
            "prefer_offline_stt": s.prefer_offline_stt,
            "prefer_offline_tts": s.prefer_offline_tts,
            "preferred_online_model": s.preferred_online_model,
            "preferred_offline_model": s.preferred_offline_model,
        }
