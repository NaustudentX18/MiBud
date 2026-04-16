"""
tests/test_config_migration.py
Config schema migration tests
"""
import sys
import json
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_config_has_schema_version():
    """Config must have a config_version field."""
    from core.config import Config
    cfg = Config()
    assert "config_version" in cfg.data, "Config must have config_version field"


def test_migration_adds_tuning_on_old_config(tmp_path, monkeypatch):
    """Loading old config without 'tuning' should trigger migration."""
    # Simulate old config
    old_config = {
        "ai": {"default_provider": "openrouter"},
        "first_run": False,
        "setup_complete": True,
        "config_version": 0,
    }
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(old_config))

    # Point Config to our tmp dir
    import core.config
    orig_save = core.config.Config.save
    def noop_save(self, config_dir=None):
        pass
    core.config.Config.save = noop_save

    try:
        from core.config import Config
        cfg = Config()
        cfg.config_file = cfg_file
        cfg.config_dir = tmp_path
        cfg.load()

        # Migration should have added 'tuning' section
        assert "tuning" in cfg.data, \
            f"Migration should add 'tuning' section. Got keys: {list(cfg.data.keys())}"
        assert cfg.data.get("config_version") == 1, \
            f"config_version should be 1 after migration, got {cfg.data.get('config_version')}"
    finally:
        core.config.Config.save = orig_save


def test_save_preserves_config_version(tmp_path):
    """Config.save() must write current config_version."""
    from core.config import Config
    cfg = Config()
    cfg.config_dir = tmp_path
    cfg.load()

    cfg.save()

    saved = json.loads((tmp_path / "config.json").read_text())
    assert "config_version" in saved
    assert saved["config_version"] == cfg.data["config_version"]


def test_migration_does_not_overwrite_existing_tuning(tmp_path):
    """Migration should not overwrite existing tuning values."""
    # Config with existing tuning but old version
    old_config = {
        "tuning": {
            "vad_threshold": 999,  # Custom value
        },
        "config_version": 0,
        "first_run": False,
    }
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(old_config))

    import core.config
    orig_save = core.config.Config.save
    def noop_save(self, config_dir=None):
        pass
    core.config.Config.save = noop_save

    try:
        from core.config import Config
        cfg = Config()
        cfg.config_file = cfg_file
        cfg.config_dir = tmp_path
        cfg.load()

        # Should keep the custom value, not overwrite it
        assert cfg.data["tuning"]["vad_threshold"] == 999, \
            "Migration should not overwrite existing tuning values"
    finally:
        core.config.Config.save = orig_save
