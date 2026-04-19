"""
MiBud Core - Proactive Engine

Runs in the background while MiBud is idle and watches for things worth
speaking up about:

- Battery crossing low / critical thresholds
- Reminders triggering at their scheduled time
- Timers completing
- Anomaly detector alerts
- Optional idle check-ins ("still with me?") gated by config
- Optional good-morning greeting at the user's first wake-up

Everything is announced through the conversation manager's TTS so the
personality's voice is preserved, and every trigger type can be disabled
from the config.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional

log = logging.getLogger("MiBud")


@dataclass
class ProactiveConfig:
    enabled: bool = True
    battery_enabled: bool = True
    low_battery_percent: int = 20
    critical_battery_percent: int = 5
    reminders_enabled: bool = True
    timers_enabled: bool = True
    idle_checkin_enabled: bool = False
    idle_checkin_minutes: int = 30
    idle_checkin_message: str = "Still here when you need me."
    anomaly_enabled: bool = True
    morning_greeting_enabled: bool = False
    morning_greeting_hour: int = 7
    quiet_hours_start: int = 23  # 11pm
    quiet_hours_end: int = 7     # 7am


class ProactiveEngine:
    """Background watcher that announces things on its own initiative."""

    def __init__(
        self,
        config: ProactiveConfig,
        *,
        battery: Any = None,
        reminder_manager: Any = None,
        timer_manager: Any = None,
        anomaly_detector: Any = None,
        speak: Optional[Callable[[str], Any]] = None,
        is_busy: Optional[Callable[[], bool]] = None,
    ) -> None:
        self.config = config
        self.battery = battery
        self.reminder_manager = reminder_manager
        self.timer_manager = timer_manager
        self.anomaly_detector = anomaly_detector
        self._speak = speak or (lambda text: None)
        self._is_busy = is_busy or (lambda: False)

        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_battery_level = None  # type: Optional[int]
        self._low_announced = False
        self._critical_announced = False
        self._last_idle_checkin: float = time.monotonic()
        self._last_morning_greeting_date: Optional[str] = None
        self._fired_reminders: set[str] = set()
        self._fired_timers: set[str] = set()
        self._last_anomaly_ts: float = 0.0

    # ---- lifecycle -----------------------------------------------------

    async def start(self) -> None:
        if self._task is not None:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="mibud-proactive")
        log.info("🟢 Proactive engine running")

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    # ---- main loop -----------------------------------------------------

    async def _loop(self) -> None:
        try:
            while self._running:
                try:
                    if self.config.enabled and not self._in_quiet_hours():
                        await self._tick()
                except Exception as e:  # pragma: no cover - runtime path
                    log.error(f"proactive tick failed: {e}")
                await asyncio.sleep(self._interval())
        except asyncio.CancelledError:
            return

    def _interval(self) -> float:
        # Cheap cadence. Enough to catch 1-min granularity without hot-polling.
        return 10.0

    def _in_quiet_hours(self) -> bool:
        h = datetime.now().hour
        start = self.config.quiet_hours_start
        end = self.config.quiet_hours_end
        if start == end:
            return False
        if start < end:
            return start <= h < end
        return h >= start or h < end

    async def _tick(self) -> None:
        if self._is_busy():
            return
        if self.config.battery_enabled:
            await self._check_battery()
        if self.config.reminders_enabled:
            await self._check_reminders()
        if self.config.timers_enabled:
            await self._check_timers()
        if self.config.anomaly_enabled:
            await self._check_anomalies()
        if self.config.morning_greeting_enabled:
            await self._maybe_morning_greeting()
        if self.config.idle_checkin_enabled:
            await self._maybe_idle_checkin()

    # ---- battery -------------------------------------------------------

    async def _check_battery(self) -> None:
        if self.battery is None:
            return
        try:
            status = self.battery.get_status()
        except Exception:
            return
        level = int(status.level)
        charging = bool(status.charging)

        if charging:
            # Reset so we announce again next time it unplugs & dips.
            self._low_announced = False
            self._critical_announced = False
            if self._last_battery_level is not None and self._last_battery_level < 30 and level >= 95:
                await self._maybe_say("Battery is fully charged.")
        else:
            if level <= self.config.critical_battery_percent and not self._critical_announced:
                await self._maybe_say(
                    f"Battery is critical at {level} percent. I'll shut down soon if you don't plug me in."
                )
                self._critical_announced = True
            elif level <= self.config.low_battery_percent and not self._low_announced:
                await self._maybe_say(f"Heads up, battery is at {level} percent.")
                self._low_announced = True

        self._last_battery_level = level

    # ---- reminders / timers -------------------------------------------

    async def _check_reminders(self) -> None:
        if self.reminder_manager is None:
            return
        due = [
            r for r in self.reminder_manager.reminders.values()
            if not r.completed and r.trigger_time <= datetime.now()
        ]
        for r in due:
            if r.id in self._fired_reminders:
                continue
            self._fired_reminders.add(r.id)
            await self._maybe_say(f"Reminder: {r.message}")
            try:
                self.reminder_manager.complete_reminder(r.id)
            except Exception:
                pass

    async def _check_timers(self) -> None:
        if self.timer_manager is None:
            return
        for t in list(self.timer_manager.timers.values()):
            if t.completed and t.id not in self._fired_timers:
                self._fired_timers.add(t.id)
                await self._maybe_say(f"Your '{t.name}' timer is done.")

    # ---- anomaly -------------------------------------------------------

    async def _check_anomalies(self) -> None:
        if self.anomaly_detector is None:
            return
        get_recent = getattr(self.anomaly_detector, "get_recent_alerts", None)
        if not callable(get_recent):
            return
        try:
            alerts = get_recent(since=self._last_anomaly_ts) or []
        except Exception:
            return
        for a in alerts:
            msg = getattr(a, "message", None) or (a.get("message") if isinstance(a, dict) else None)
            if not msg:
                continue
            await self._maybe_say(f"Alert: {msg}")
        self._last_anomaly_ts = time.time()

    # ---- idle check-in / morning greeting ------------------------------

    async def _maybe_idle_checkin(self) -> None:
        elapsed = (time.monotonic() - self._last_idle_checkin) / 60.0
        if elapsed >= self.config.idle_checkin_minutes:
            self._last_idle_checkin = time.monotonic()
            await self._maybe_say(self.config.idle_checkin_message)

    async def _maybe_morning_greeting(self) -> None:
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        if self._last_morning_greeting_date == today:
            return
        if now.hour == self.config.morning_greeting_hour:
            self._last_morning_greeting_date = today
            hour_word = "morning" if now.hour < 12 else "afternoon"
            await self._maybe_say(f"Good {hour_word}. I'm ready whenever you are.")

    # ---- speak helper --------------------------------------------------

    async def _maybe_say(self, text: str) -> None:
        if self._is_busy():
            return
        try:
            result = self._speak(text)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:  # pragma: no cover - runtime path
            log.error(f"proactive speak failed: {e}")

    # ---- admin hooks ---------------------------------------------------

    def reset_announcements(self) -> None:
        self._low_announced = False
        self._critical_announced = False
        self._fired_reminders.clear()
        self._fired_timers.clear()
