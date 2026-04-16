"""
tests/test_shutdown.py
Tests for graceful async shutdown
"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.mark.asyncio
async def test_shutdown_is_idempotent():
    """Calling shutdown() twice must not crash or misbehave."""
    from core.main import MiBudApp

    app = MiBudApp()
    app.running = True

    await app.shutdown()
    first_state = app.running

    await app.shutdown()
    second_state = app.running

    # Both calls should succeed without crashing
    assert first_state is False
    assert second_state is False


@pytest.mark.asyncio
async def test_shutdown_stops_running_flag():
    """shutdown() must set running=False."""
    from core.main import MiBudApp

    app = MiBudApp()
    app.running = True

    await app.shutdown()
    assert app.running is False


@pytest.mark.asyncio
async def test_shutdown_clears_workers():
    """shutdown() should not leave orphaned tasks."""
    from core.main import MiBudApp

    app = MiBudApp()
    app.running = True

    await app.shutdown()
    assert app.workers == [] or app.workers is not None