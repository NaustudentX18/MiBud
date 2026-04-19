"""
Tests for the tool-use / function-calling layer.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from ai.tools import (
    ToolCall,
    ToolRegistry,
    ToolContext,
    build_builtin_tools,
    get_registry,
    run_tool_calls,
    tool,
)


def test_decorator_infers_schema_from_hints_and_doc():
    reg = ToolRegistry()

    @tool(registry=reg)
    def greet(name: str, enthusiastic: bool = False) -> str:
        """Return a personal greeting.

        name: who to greet
        enthusiastic: add exclamation marks
        """
        return ("Hi " + name + ("!" if enthusiastic else ""))

    spec = reg.get("greet")
    assert spec is not None
    assert "personal greeting" in spec.description
    by_name = {p.name: p for p in spec.params}
    assert by_name["name"].type == "string"
    assert by_name["name"].required is True
    assert by_name["name"].description == "who to greet"
    assert by_name["enthusiastic"].type == "boolean"
    assert by_name["enthusiastic"].required is False


def test_schema_adapters_shape():
    reg = ToolRegistry()

    @tool(registry=reg, enums={"units": ["c", "f"]})
    def weather(city: str, units: str = "c") -> dict:
        """Look up the weather.

        city: the city name
        units: temperature units (c or f)
        """
        return {"city": city, "units": units}

    openai_schema = reg.get("weather").to_openai()
    assert openai_schema["type"] == "function"
    assert openai_schema["function"]["name"] == "weather"
    assert openai_schema["function"]["parameters"]["properties"]["units"]["enum"] == ["c", "f"]

    anthropic_schema = reg.get("weather").to_anthropic()
    assert "input_schema" in anthropic_schema
    assert "city" in anthropic_schema["input_schema"]["required"]

    gemini_schema = reg.get("weather").to_google()
    # Gemini uses uppercase types.
    assert gemini_schema["parameters"]["properties"]["city"]["type"] == "STRING"


def test_invoke_unknown_tool_returns_error():
    reg = ToolRegistry()
    out = asyncio.run(reg.invoke("nope", {}))
    assert out["ok"] is False
    assert "unknown" in out["error"]


def test_invoke_filters_extra_args():
    reg = ToolRegistry()

    @tool(registry=reg)
    def echo(x: int) -> int:
        """Echo an int. x: number"""
        return x * 2

    out = asyncio.run(reg.invoke("echo", {"x": 5, "evil": "rm -rf"}))
    assert out["ok"] is True
    assert out["result"] == 10


def test_invoke_bad_args_are_reported():
    reg = ToolRegistry()

    @tool(registry=reg)
    def strict(x: int) -> int:
        """Need x. x: number"""
        return x

    out = asyncio.run(reg.invoke("strict", {}))
    assert out["ok"] is False
    assert "bad arguments" in out["error"]


def test_invoke_handles_async_tool_and_exceptions():
    reg = ToolRegistry()

    @tool(registry=reg)
    async def boom() -> None:
        """Always fails."""
        raise RuntimeError("kaboom")

    out = asyncio.run(reg.invoke("boom", {}))
    assert out["ok"] is False
    assert "kaboom" in out["error"]


def test_invoke_times_out():
    reg = ToolRegistry()

    @tool(registry=reg)
    async def slow() -> None:
        """sleep forever"""
        await asyncio.sleep(10)

    out = asyncio.run(reg.invoke("slow", {}, timeout=0.1))
    assert out["ok"] is False
    assert "timeout" in out["error"]


def test_run_tool_calls_parallel():
    reg = ToolRegistry()

    @tool(registry=reg)
    def add(a: int, b: int) -> int:
        """Add two.

        a: x
        b: y
        """
        return a + b

    calls = [
        ToolCall(id="t1", name="add", arguments={"a": 1, "b": 2}),
        ToolCall(id="t2", name="add", arguments={"a": 3, "b": 4}),
    ]
    results = asyncio.run(run_tool_calls(calls, registry=reg))
    out = {r.id: r.content for r in results}
    assert out == {"t1": 3, "t2": 7}


def test_builtin_tools_registered_with_context():
    reg = ToolRegistry()

    class FakeBattery:
        def get_status(self):
            from hardware.battery import BatteryStatus
            return BatteryStatus(level=42, voltage=3.7, charging=True)

    class FakeReminder:
        def __init__(self):
            self.reminders = {}
        def create_reminder_relative(self, msg, m):
            return "r1"
        def get_upcoming_reminders(self, limit=5):
            return []

    class FakeTimer:
        def __init__(self):
            self.timers = {}
            self.cancelled = []
        def create_timer(self, name, seconds):
            self.timers[name] = (name, seconds)
            return name
        def get_active_timers(self):
            return []
        def cancel_timer(self, tid):
            self.cancelled.append(tid)
            return True

    ctx = ToolContext(
        battery=FakeBattery(),
        reminder_manager=FakeReminder(),
        timer_manager=FakeTimer(),
    )
    build_builtin_tools(ctx, registry=reg)
    names = set(reg.names())
    for must in ("get_time", "get_battery", "set_timer", "create_reminder",
                 "list_reminders", "list_timers", "add_note", "search_notes"):
        assert must in names, f"missing tool {must}"

    # Battery tool works.
    out = asyncio.run(reg.invoke("get_battery", {}))
    assert out["ok"] and out["result"]["level_percent"] == 42
    assert out["result"]["charging"] is True

    # Timer creation.
    out = asyncio.run(reg.invoke("set_timer", {"name": "tea", "seconds": 90}))
    assert out["ok"]
    assert out["result"]["timer_id"] == "tea"


def test_tool_registry_is_singleton_accessible():
    # The global registry should be accessible without arguments.
    reg = get_registry()
    assert reg is get_registry()
