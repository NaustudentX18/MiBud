import json
import pytest
import importlib
from pathlib import Path


def test_api_keys_never_written_to_disk(tmp_path, monkeypatch):
    """API keys must NEVER be persisted to config.json"""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret-key-123")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key-456")

    import core.config
    importlib.reload(core.config)

    cfg = core.config.Config()
    cfg.config_dir = tmp_path
    cfg.config_file = tmp_path / "config.json"
    cfg.config_dir.mkdir(parents=True, exist_ok=True)

    # Simulate save (happens on setup complete)
    cfg.save()

    # Reload and verify
    with open(cfg.config_file) as f:
        saved = json.load(f)

    # API keys must NOT appear anywhere in saved config
    assert "api_keys" not in saved, "api_keys section must NOT be in config.json"
    # Traverse all nested dicts to be sure
    def find_api_keys(d, path=""):
        if isinstance(d, dict):
            for k, v in d.items():
                assert k != "api_keys", f"Found 'api_keys' at {path}.{k}"
                find_api_keys(v, f"{path}.{k}")
        return True
    find_api_keys(saved)


def test_api_keys_loaded_from_env(monkeypatch):
    """get_api_key() must return value from env var"""
    monkeypatch.setenv("OPENAI_API_KEY", "env-secret-xyz")
    import core.config
    importlib.reload(core.config)

    cfg = core.config.Config()
    assert cfg.get_api_key("openai") == "env-secret-xyz"


def test_has_api_key_true_when_env_set(monkeypatch):
    """has_api_key() must return True when env var is set"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real")
    import core.config
    importlib.reload(core.config)

    cfg = core.config.Config()
    assert cfg.has_api_key("anthropic") == True
    assert cfg.has_api_key("nonexistent_provider") == False
