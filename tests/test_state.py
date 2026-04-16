"""
tests/test_state.py
State machine tests — ERROR state auto-recovery
"""
import pytest
import sys
import asyncio
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_state_manager_initial_state():
    """StateManager starts in IDLE state."""
    from core.state import StateManager
    sm = StateManager()
    assert sm.get_state() == "idle"


@pytest.mark.asyncio
async def test_set_state_accepts_string():
    """set_state must accept string values like 'error'."""
    from core.state import StateManager
    sm = StateManager()
    sm.set_state("error")
    assert sm.get_state() == "error"


@pytest.mark.asyncio
async def test_error_state_auto_recovery():
    """ERROR state should auto-recover to IDLE after timeout."""
    from core.state import StateManager

    sm = StateManager()
    sm._error_recovery_timeout = 0.1  # 100ms for fast test

    sm.set_state("error")
    assert sm.get_state() == "error"

    # Wait for recovery timeout via the event loop
    await asyncio.sleep(0.3)

    # Auto-recovery should have transitioned back
    assert sm.get_state() == "idle", \
        f"ERROR state did not auto-recover. Current state: {sm.get_state()}"


@pytest.mark.asyncio
async def test_error_recovery_callback():
    """StateManager should call callbacks on ERROR→IDLE recovery."""
    from core.state import StateManager

    sm = StateManager()
    sm._error_recovery_timeout = 0.1

    transitions = []
    def transition_logger(old, new):
        transitions.append((old.value, new.value))

    sm.register_state_callback(transition_logger)

    sm.set_state("error")
    await asyncio.sleep(0.3)

    # Should have logged: error→idle transition
    assert ("error", "idle") in transitions, \
        f"Expected error→idle transition, got {transitions}"
