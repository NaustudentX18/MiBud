"""
core/health.py
Per-subsystem hardware health monitoring
"""

import logging
from dataclasses import dataclass
from typing import Optional, Dict

log = logging.getLogger("MiBud")


@dataclass
class HealthResult:
    """Result of a health check"""
    subsystem: str
    healthy: bool
    can_proceed: bool  # True = non-critical, system can continue
    message: str = ""


class HealthMonitor:
    """Monitors hardware subsystem health"""

    def __init__(self):
        self._results: Dict[str, HealthResult] = {}
        self.HealthResult = HealthResult  # expose on instance for tests

    async def check_audio(self, audio) -> HealthResult:
        """Check audio subsystem health"""
        try:
            if audio is None:
                return HealthResult(
                    subsystem="audio",
                    healthy=False,
                    can_proceed=False,
                    message="Audio manager not initialized"
                )

            # Try to read audio level as a basic health check
            level = audio.get_level()
            return HealthResult(
                subsystem="audio",
                healthy=True,
                can_proceed=True,
                message=f"Audio OK (level={level})"
            )
        except Exception as e:
            return HealthResult(
                subsystem="audio",
                healthy=False,
                can_proceed=False,
                message=f"Audio check failed: {e}"
            )

    async def check_display(self, display) -> HealthResult:
        """Check display subsystem health"""
        try:
            if display is None:
                return HealthResult(
                    subsystem="display",
                    healthy=False,
                    can_proceed=True,  # Display is optional
                    message="Display not available — using mock"
                )
            return HealthResult(
                subsystem="display",
                healthy=True,
                can_proceed=True,
                message="Display OK"
            )
        except Exception as e:
            return HealthResult(
                subsystem="display",
                healthy=False,
                can_proceed=True,
                message=f"Display check failed: {e}"
            )

    async def check_battery(self, battery) -> HealthResult:
        """Check battery subsystem health"""
        try:
            if battery is None:
                return HealthResult(
                    subsystem="battery",
                    healthy=False,
                    can_proceed=True,  # Battery is optional
                    message="Battery not available"
                )
            level = battery.get_level()
            return HealthResult(
                subsystem="battery",
                healthy=True,
                can_proceed=True,
                message=f"Battery OK ({level}%)"
            )
        except Exception as e:
            return HealthResult(
                subsystem="battery",
                healthy=False,
                can_proceed=True,
                message=f"Battery check failed: {e}"
            )

    async def run_all(self, audio=None, display=None, battery=None) -> Dict[str, HealthResult]:
        """Run all health checks"""
        results = {}

        results["audio"] = await self.check_audio(audio)
        results["display"] = await self.check_display(display)
        results["battery"] = await self.check_battery(battery)

        for name, result in results.items():
            if not result.healthy:
                status = "❌" if not result.can_proceed else "⚠️"
                log.warning(f"{status} Health check [{name}]: {result.message}")
            else:
                log.info(f"✅ Health check [{name}]: {result.message}")

        self._results = results
        return results

    def can_proceed(self) -> tuple[bool, list[str]]:
        """Check if startup can proceed based on health results.

        Returns (can_proceed, failed_subsystems)
        """
        failed = []
        for sub, result in self._results.items():
            if not result.can_proceed and not result.healthy:
                failed.append(sub)
        return len(failed) == 0, failed