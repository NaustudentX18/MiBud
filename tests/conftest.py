"""
tests/conftest.py
Shared pytest fixtures for web API tests
"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def app_with_test_env(monkeypatch, tmp_path):
    """Set up Flask app with test config and empty PIN (no auth set)."""
    monkeypatch.setenv("FLASK_ENV", "testing")

    # Point config dir to tmp location for isolation
    test_config = tmp_path / "config"
    test_config.mkdir()
    # Write empty pin hash — means no PIN is configured
    (test_config / ".pin_hash").write_text("")

    # Patch the pin file path in auth module
    import web.auth
    monkeypatch.setattr(web.auth, "_PIN_HASH_FILE", test_config / ".pin_hash")

    import web.server
    web.server.app.config["TESTING"] = True
    web.server.app.config["SECRET_KEY"] = "test-secret"

    with web.server.app.test_client() as client:
        yield client

    # Cleanup pin file
    pin_file = Path(__file__).parent.parent / "config" / ".pin_hash"
    if pin_file.exists():
        pin_file.unlink()


# Alias for test_web_errors.py
client = app_with_test_env
