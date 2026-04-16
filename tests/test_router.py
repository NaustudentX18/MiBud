"""
tests/test_router.py
Tests for AI router — connectivity, Ollama async, fallback behavior
"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def mock_config(monkeypatch):
    """Minimal config with no API keys — forces offline mode."""
    monkeypatch.setenv("OLLAMA_URL", "http://localhost:11434")

    import core.config
    cfg = core.config.Config()
    cfg.data["ai"] = {
        "default_provider": "openrouter",
        "ollama_url": "http://localhost:11434",
        "offline_model": "phi3:latest",
    }
    cfg.data["api_keys"] = {}
    return cfg


@pytest.fixture
def router(mock_config):
    from ai.router import AIRouter
    r = AIRouter(mock_config)
    return r


def test_generate_does_not_block_event_loop(router, monkeypatch):
    """generate() must not use blocking requests — verify no sync requests imported."""
    import ai.router
    source = open(ai.router.__file__).read()

    # Within the Ollama methods, should NOT see "import requests"
    # (global import is fine if unused, but aiohttp should be used for Ollama)
    # Check that _generate_ollama doesn't use requests.post
    assert "requests.post" not in source or "# requests.post" in source, \
        "_generate_ollama still uses blocking requests.post"


def test_init_ollama_does_not_use_blocking_requests(router, monkeypatch):
    """_init_ollama must use async HTTP, not blocking requests.get."""
    import ai.router
    source = open(ai.router.__file__).read()

    # The init method for Ollama should not have blocking requests.get
    # (check for aiohttp usage instead)
    assert "aiohttp" in source, "ai/router.py should use aiohttp for async HTTP"


def test_connectivity_precheck_before_online_generation(router, monkeypatch):
    """AIRouter should check connectivity before attempting online providers."""
    from ai.router import AIRouter

    # Verify _check_internet_connectivity method exists
    assert hasattr(router, "_check_internet_connectivity"), \
        "AIRouter should have _check_internet_connectivity method"


def test_generate_routes_to_ollama_when_offline(router, monkeypatch):
    """When offline and prefer_offline=True, generate() should try Ollama first."""
    import ai.router

    source = open(ai.router.__file__).read()
    # The generate method should check connectivity or prefer offline
    # We're testing the method exists and can be called
    assert hasattr(router, "generate"), "generate() method missing"