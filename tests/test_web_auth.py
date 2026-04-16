"""
tests/test_web_auth.py
TDD tests for PIN gate auth on Flask web API
"""

import pytest
import sys
from pathlib import Path

# Ensure project root on path
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


def test_writable_endpoints_require_auth(app_with_test_env):
    """POST /api/keys/save must require auth when no PIN is set."""
    resp = app_with_test_env.post("/api/keys/save", json={"keys": {}})
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


def test_config_save_requires_auth(app_with_test_env):
    """POST /api/config/save must require auth."""
    resp = app_with_test_env.post("/api/config/save", json={})
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


def test_personality_set_requires_auth(app_with_test_env):
    """POST /api/personality/set must require auth."""
    resp = app_with_test_env.post("/api/personality/set", json={"personality": "assistant"})
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


def test_personality_create_requires_auth(app_with_test_env):
    """POST /api/personality/create must require auth."""
    resp = app_with_test_env.post("/api/personality/create", json={})
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


def test_personality_update_requires_auth(app_with_test_env):
    """PUT /api/personality/<id> must require auth."""
    resp = app_with_test_env.put("/api/personality/custom_id", json={})
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


def test_personality_delete_requires_auth(app_with_test_env):
    """DELETE /api/personality/<id> must require auth."""
    resp = app_with_test_env.delete("/api/personality/custom_id")
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


def test_mission_settings_requires_auth(app_with_test_env):
    """POST /api/mission/settings must require auth."""
    resp = app_with_test_env.post("/api/mission/settings", json={"path": "features.enable_tts", "value": True})
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


def test_mission_provider_requires_auth(app_with_test_env):
    """POST /api/mission/provider must require auth."""
    resp = app_with_test_env.post("/api/mission/provider", json={"provider": "openrouter"})
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


def test_camera_enable_requires_auth(app_with_test_env):
    """POST /api/camera/enable must require auth."""
    resp = app_with_test_env.post("/api/camera/enable", json={"enabled": True})
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


def test_alerts_clear_requires_auth(app_with_test_env):
    """POST /api/alerts/clear must require auth."""
    resp = app_with_test_env.post("/api/alerts/clear")
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}"


def test_read_endpoints_open_or_authd(app_with_test_env):
    """GET /api/providers should work without auth (read-only)."""
    resp = app_with_test_env.get("/api/providers")
    # Open endpoint — no auth needed
    assert resp.status_code == 200


def test_status_endpoint_works(app_with_test_env):
    """GET /api/status should work without auth."""
    resp = app_with_test_env.get("/api/status")
    assert resp.status_code == 200


def test_personality_list_open(app_with_test_env):
    """GET /api/personality/list should be open (read-only)."""
    resp = app_with_test_env.get("/api/personality/list")
    assert resp.status_code == 200


def test_system_info_open(app_with_test_env):
    """GET /api/system/info should be open (read-only)."""
    resp = app_with_test_env.get("/api/system/info")
    assert resp.status_code == 200


def test_auth_with_valid_pin_header(app_with_test_env, monkeypatch):
    """Provide correct X-MiBud-PIN header to access protected endpoint."""
    import hashlib
    test_pin = "1234"

    # Set up a known PIN in the test pin file
    import web.auth
    pin_hash = hashlib.sha256(test_pin.encode()).hexdigest()
    web.auth._PIN_HASH_FILE.write_text(pin_hash)

    # Now request with correct PIN in header
    resp = app_with_test_env.post(
        "/api/keys/save",
        json={"keys": {}},
        headers={"X-MiBud-PIN": test_pin}
    )
    # Should succeed now
    assert resp.status_code == 200, f"Expected 200 with valid PIN, got {resp.status_code}"


def test_pin_set_endpoint(app_with_test_env):
    """POST /api/pin/set should set the PIN and return success."""
    resp = app_with_test_env.post("/api/pin/set", json={"pin": "9999"})
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    data = resp.get_json()
    assert data.get("success") is True


def test_pin_set_rejects_short_pin(app_with_test_env):
    """POST /api/pin/set should reject PINs shorter than 4 chars."""
    resp = app_with_test_env.post("/api/pin/set", json={"pin": "12"})
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"
