"""
Tests for the PowerManager profile switching logic.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.power import PowerManager, PowerManagerConfig, PowerProfile


class FakeBatteryStatus:
    def __init__(self, level: int, charging: bool = False):
        self.level = level
        self.charging = charging


class FakeBattery:
    def __init__(self, level: int, charging: bool = False):
        self._status = FakeBatteryStatus(level, charging)

    def get_status(self):
        return self._status

    def set(self, level: int, charging: bool = False):
        self._status = FakeBatteryStatus(level, charging)


def test_defaults_to_balanced():
    pm = PowerManager(PowerManagerConfig(), battery=FakeBattery(70))
    pm._evaluate()
    assert pm.get_current_name() == "balanced"


def test_low_battery_switches_to_eco():
    battery = FakeBattery(10)
    pm = PowerManager(PowerManagerConfig(eco_below_percent=25), battery=battery)
    pm._evaluate()
    assert pm.get_current_name() == "eco"


def test_charging_switches_to_performance():
    battery = FakeBattery(90, charging=True)
    pm = PowerManager(PowerManagerConfig(performance_on_charge=True), battery=battery)
    pm._evaluate()
    assert pm.get_current_name() == "performance"


def test_manual_override_sticks_until_auto():
    battery = FakeBattery(5)
    pm = PowerManager(PowerManagerConfig(), battery=battery)
    pm.set_manual(PowerProfile.PERFORMANCE)
    assert pm.get_current_name() == "performance"
    # Auto would pick ECO at 5% — but we're manual.
    pm._evaluate()
    assert pm.get_current_name() == "performance"
    pm.set_auto()
    assert pm.get_current_name() == "eco"


def test_listener_fires_on_change():
    received = []
    battery = FakeBattery(70)
    pm = PowerManager(PowerManagerConfig(), battery=battery)
    pm.subscribe(lambda s: received.append(s.name.value))
    pm._evaluate()  # balanced (no change from default)
    battery.set(10)
    pm._evaluate()  # -> eco
    battery.set(90, charging=True)
    pm._evaluate()  # -> performance
    assert received == ["eco", "performance"]


def test_snapshot_exposes_profile_fields():
    pm = PowerManager(PowerManagerConfig(), battery=FakeBattery(70))
    pm._evaluate()
    snap = pm.snapshot()
    assert snap["profile"] == "balanced"
    assert snap["ai_max_tokens"] > 0
    assert snap["display_brightness"] > 0
