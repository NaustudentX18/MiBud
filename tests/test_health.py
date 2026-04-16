"""
tests/test_health.py
Per-subsystem health checks for MiBud hardware
"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.mark.asyncio
async def test_health_monitor_has_health_result_class():
    """HealthMonitor should define a HealthResult dataclass."""
    from core.health import HealthMonitor
    hm = HealthMonitor()
    assert hasattr(hm, 'HealthResult') or hasattr(hm, '_result_class'), "HealthMonitor should have HealthResult"


@pytest.mark.asyncio
async def test_check_audio_handles_none_gracefully():
    """check_audio must return a result (not raise) when audio is None."""
    from core.health import HealthMonitor

    monitor = HealthMonitor()
    result = await monitor.check_audio(None)
    assert result is not None
    assert result.healthy is False


@pytest.mark.asyncio
async def test_can_proceed_requires_audio():
    """can_proceed must return False when audio is unhealthy."""
    from core.health import HealthMonitor

    monitor = HealthMonitor()
    # Manually set an unhealthy audio result
    result = monitor.HealthResult(subsystem="audio", healthy=False, can_proceed=False, message="no audio")
    monitor._results["audio"] = result
    can_go, failed = monitor.can_proceed()
    assert can_go is False
    assert "audio" in failed


@pytest.mark.asyncio
async def test_run_all_checks_all_subsystems():
    """run_all() should check audio, display, and battery."""
    from core.health import HealthMonitor

    monitor = HealthMonitor()
    results = await monitor.run_all(audio=None, display=None, battery=None)
    assert "audio" in results
    assert "display" in results
    assert "battery" in results