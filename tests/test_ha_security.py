"""
tests/test_ha_security.py
Home Assistant token must come from env vars — never persisted to disk
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_ha_client_reads_token_from_env(monkeypatch):
    """HomeAssistantClient must read HA_TOKEN from environment, not config."""
    monkeypatch.setenv("HA_TOKEN", "my_secret_ha_token")

    # Force reimport to pick up env
    import importlib
    if "home.automation" in sys.modules:
        del sys.modules["home.automation"]
    if "core.config" in sys.modules:
        del sys.modules["core.config"]

    from core.config import Config
    from home.automation import HomeAssistantClient

    config = Config()
    client = HomeAssistantClient(config)
    assert client.token == "my_secret_ha_token", f"Expected 'my_secret_ha_token', got '{client.token}'"


def test_ha_client_env_takes_precedence_over_config(monkeypatch, tmp_path):
    """Env var HA_TOKEN must take precedence over config-stored token."""
    monkeypatch.setenv("HA_TOKEN", "env优先_token")

    # Clear modules
    for mod in list(sys.modules.keys()):
        if mod.startswith("home.") or mod.startswith("core."):
            del sys.modules[mod]

    from core.config import Config
    from home.automation import HomeAssistantClient

    config = Config()
    # Manually set a conflicting token in config data
    config.data["home_assistant"] = {"url": "http://ha.local", "token": "disk_token_never_use"}

    client = HomeAssistantClient(config)
    assert client.token == "env优先_token", f"Env token should win, got '{client.token}'"


def test_ha_token_never_in_saved_config_data(monkeypatch, tmp_path):
    """HA token key must not appear in config.json save data."""
    monkeypatch.setenv("HA_TOKEN", "seekrit_token")

    # Clear modules
    for mod in list(sys.modules.keys()):
        if mod.startswith("home.") or mod.startswith("core."):
            del sys.modules[mod]

    from core.config import Config

    config = Config()
    config.config_dir = tmp_path
    config.config_file = tmp_path / "config.json"
    config.load()

    # Trigger a save
    config.save()

    # Read saved config
    import json
    saved = json.loads((tmp_path / "config.json").read_text())

    # HA token must not be in saved data
    ha_data = saved.get("home_assistant", {})
    assert "token" not in str(ha_data).lower(), f"Token leaked to disk: {ha_data}"
