"""
Tests for the router's retry / circuit-breaker plumbing.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from ai.router import AIResponse, AIRouter, ChatMessage, CircuitBreaker, _with_retry


def test_circuit_breaker_opens_after_failures():
    cb = CircuitBreaker(max_failures=2, cool_seconds=10)
    assert cb.allow() is True
    cb.on_failure()
    assert cb.allow() is True
    cb.on_failure()
    assert cb.allow() is False  # breaker open


def test_circuit_breaker_half_open_after_cool_period():
    cb = CircuitBreaker(max_failures=1, cool_seconds=0.05)
    cb.on_failure()
    assert cb.allow() is False
    time.sleep(0.06)
    assert cb.allow() is True  # half-open allows one retry
    cb.on_success()
    assert cb.allow() is True


def test_with_retry_eventually_succeeds():
    calls = {"n": 0}

    async def sometimes():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("flaky")
        return "ok"

    result = asyncio.run(_with_retry(lambda: sometimes(), attempts=4, base_delay=0.001))
    assert result == "ok"
    assert calls["n"] == 3


def test_with_retry_raises_after_all_attempts():
    async def always():
        raise RuntimeError("dead")

    with pytest.raises(RuntimeError, match="dead"):
        asyncio.run(_with_retry(lambda: always(), attempts=2, base_delay=0.001))


class _FakeConfig:
    def __init__(self):
        self._api = {"openai": "", "anthropic": "", "google": "",
                     "deepseek": "", "openrouter": ""}
        self._get = {
            "ai.default_provider": "openrouter",
            "ai.ollama_url": "http://127.0.0.1:1",
            "ai.offline_model": "phi3:latest",
            "tuning.ai_max_tokens": 200,
        }

    def get(self, k, default=None):
        return self._get.get(k, default)

    def get_api_key(self, p):
        return self._api.get(p, "")

    def has_api_key(self, p):
        return bool(self._api.get(p))


def test_provider_order_prefers_default_then_fallbacks():
    cfg = _FakeConfig()
    router = AIRouter(cfg)
    # Simulate only openrouter + ollama initialised.
    router._providers = {
        "openrouter": {"client": object(), "supports_tools": True},
        "openai": {"client": object(), "supports_tools": True},
    }
    order = router._provider_order(prefer_offline=False)
    assert order[0] == "openrouter"
    assert "openai" in order
    # And with prefer_offline when ollama is available.
    router._providers["ollama"] = {"available": True, "url": "", "supports_tools": False}
    order_off = router._provider_order(prefer_offline=True)
    assert order_off[0] == "ollama"
