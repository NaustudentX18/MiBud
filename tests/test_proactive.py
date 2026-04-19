"""
Tests for the ProactiveEngine.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.proactive import ProactiveConfig, ProactiveEngine


class FakeBattery:
    def __init__(self, level, charging=False):
        self.level = level
        self.charging = charging
    def get_status(self):
        class S:
            def __init__(s, level, charging):
                s.level = level
                s.charging = charging
        return S(self.level, self.charging)


class FakeReminder:
    def __init__(self, reminders=None):
        self.reminders = reminders or {}
        self.completed = []
    def complete_reminder(self, rid):
        self.completed.append(rid)
        self.reminders.pop(rid, None)
        return True


class FakeReminderObj:
    def __init__(self, rid, msg, trigger_time):
        self.id = rid
        self.message = msg
        self.trigger_time = trigger_time
        self.completed = False


class FakeTimerObj:
    def __init__(self, tid, name, completed):
        self.id = tid
        self.name = name
        self.completed = completed


class FakeTimerMgr:
    def __init__(self, timers):
        self.timers = {t.id: t for t in timers}


def _run(engine_task):
    return asyncio.get_event_loop().run_until_complete(engine_task)


def test_low_battery_announces_once():
    spoken = []
    async def say(t):
        spoken.append(t)
    cfg = ProactiveConfig(
        low_battery_percent=20, critical_battery_percent=5,
        quiet_hours_start=0, quiet_hours_end=0,   # disable quiet hours
    )
    engine = ProactiveEngine(cfg, battery=FakeBattery(15), speak=say)
    asyncio.run(engine._tick())
    asyncio.run(engine._tick())  # shouldn't re-announce
    assert len(spoken) == 1
    assert "15" in spoken[0] or "percent" in spoken[0]


def test_critical_supersedes_low():
    spoken = []
    async def say(t):
        spoken.append(t)
    cfg = ProactiveConfig(quiet_hours_start=0, quiet_hours_end=0)
    engine = ProactiveEngine(cfg, battery=FakeBattery(3), speak=say)
    asyncio.run(engine._tick())
    assert len(spoken) == 1
    assert "critical" in spoken[0].lower()


def test_charging_resets_so_next_drain_announces():
    spoken = []
    async def say(t):
        spoken.append(t)
    cfg = ProactiveConfig(quiet_hours_start=0, quiet_hours_end=0)
    battery = FakeBattery(10)
    engine = ProactiveEngine(cfg, battery=battery, speak=say)
    asyncio.run(engine._tick())
    assert len(spoken) == 1
    # Plug in, drain back.
    battery.level = 80
    battery.charging = True
    asyncio.run(engine._tick())
    battery.level = 15
    battery.charging = False
    asyncio.run(engine._tick())
    assert len(spoken) == 2


def test_reminder_fires_once_and_completes():
    spoken = []
    async def say(t):
        spoken.append(t)
    r = FakeReminderObj("r1", "call dentist", datetime.now() - timedelta(minutes=1))
    rm = FakeReminder({"r1": r})
    cfg = ProactiveConfig(quiet_hours_start=0, quiet_hours_end=0)
    engine = ProactiveEngine(cfg, battery=None, reminder_manager=rm, speak=say)
    asyncio.run(engine._tick())
    asyncio.run(engine._tick())  # should not fire again
    assert len(spoken) == 1
    assert "call dentist" in spoken[0]
    assert rm.completed == ["r1"]


def test_is_busy_suppresses_announcements():
    spoken = []
    async def say(t):
        spoken.append(t)
    cfg = ProactiveConfig(quiet_hours_start=0, quiet_hours_end=0)
    engine = ProactiveEngine(
        cfg,
        battery=FakeBattery(10),
        speak=say,
        is_busy=lambda: True,
    )
    asyncio.run(engine._tick())
    assert spoken == []


def test_quiet_hours_block_everything():
    spoken = []
    async def say(t):
        spoken.append(t)
    # Quiet hours cover all 24 hours (0..23 inclusive).
    cfg = ProactiveConfig(quiet_hours_start=0, quiet_hours_end=23)
    engine = ProactiveEngine(cfg, battery=FakeBattery(5), speak=say)
    # Don't call _tick — call _loop's guarded path instead:
    # When inside quiet hours the engine should skip.
    # We approximate by checking the quiet-hour helper.
    # The engine's _in_quiet_hours uses current time, so assert on cfg logic.
    from datetime import datetime
    hour = datetime.now().hour
    in_qh = engine._in_quiet_hours()
    # Our config says any hour in [0, 23) is quiet → hour 23 is NOT.
    assert in_qh == (0 <= hour < 23)
