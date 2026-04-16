"""
MiBud Web Server
Flask-based web interface for setup wizard and dashboard
"""

import asyncio
import json
import logging
import os
import socket
import time
from copy import deepcopy
from pathlib import Path
from urllib import error as urlerror
from urllib import request as urlrequest

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from web.auth import require_auth

log = logging.getLogger("MiBud")

# Create Flask app
app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.urandom(24)


def _sanitize_error_message(message: str) -> str:
    """Remove file paths from error messages so nothing leaks to clients."""
    import re
    # Strip Python traceback file references: "File '/path/file.py', line N"
    message = re.sub(r'File "[^"]+\.py",?\s*line\s*\d+', "", message)
    message = re.sub(r"File '[^']+\.py',?\s*line\s*\d+", "", message)
    # Strip standalone paths ending in .py:\d+ or .py", line N
    message = re.sub(r'/?[^:"\s]+\.py:\d+', "", message)
    message = re.sub(r'/?[^:\'\s]+\.py",?\s*line\s*\d+', "", message)
    # Collapse multiple spaces
    message = re.sub(r"  +", " ", message).strip()
    return message


@app.errorhandler(Exception)
def handle_exception(exc):
    """Global error handler — log full traceback server-side, return clean JSON to client."""
    log.error("Unhandled API error", exc_info=True)
    code = getattr(exc, "code", 500)
    raw = getattr(exc, "message", None) or str(exc)
    message = _sanitize_error_message(raw)
    if not message:
        message = type(exc).__name__
    if request.path.startswith("/api/"):
        return jsonify({
            "success": False,
            "error": message,
            "type": exc.__class__.__name__,
        }), code
    return {"error": message}, code

PROVIDER_CATALOG = {
    "openrouter": {
        "name": "OpenRouter (Free)",
        "models": [
            "google/gemini-2.0-flash-lite:free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "mistralai/mixtral-8x7b-instruct:free",
        ],
        "requires_key": True,
    },
    "openai": {
        "name": "OpenAI",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1-mini"],
        "requires_key": True,
    },
    "anthropic": {
        "name": "Anthropic Claude",
        "models": ["claude-3-5-sonnet-latest", "claude-3-haiku-latest"],
        "requires_key": True,
    },
    "google": {
        "name": "Google Gemini",
        "models": ["gemini-2.0-flash", "gemini-1.5-flash"],
        "requires_key": True,
    },
    "deepseek": {
        "name": "DeepSeek",
        "models": ["deepseek-chat"],
        "requires_key": True,
    },
    "ollama": {
        "name": "Ollama (Offline)",
        "models": ["phi3:latest", "tinyllama:latest", "mistral:latest"],
        "requires_key": False,
    },
}

MISSION_BOOL_PATHS = {
    "features.enable_tts",
    "features.enable_stt",
    "features.enable_weather",
    "features.enable_anomaly_detection",
    "features.enable_camera",
    "wake_word.enabled",
}
MISSION_STRING_PATHS = {"ai.ollama_url"}


def _config_path() -> Path:
    return Path(__file__).parent.parent / "config" / "config.json"


def _default_config() -> dict:
    """Get a fresh config dict with project defaults."""
    try:
        from core.config import Config

        return deepcopy(Config().data)
    except Exception as exc:
        log.warning("Falling back to minimal defaults: %s", exc)
        return {
            "ai": {
                "default_provider": "openrouter",
                "model": "google/gemini-2.0-flash-lite:free",
                "offline_model": "phi3:latest",
                "ollama_url": "http://localhost:11434",
            },
            "api_keys": {},
            "personality": {"current": "assistant"},
            "wake_word": {"enabled": True},
            "features": {
                "enable_tts": True,
                "enable_stt": True,
                "enable_weather": True,
                "enable_anomaly_detection": False,
                "enable_camera": False,
            },
            "first_run": True,
            "setup_complete": False,
        }


def _deep_merge(base: dict, override: dict) -> dict:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _load_config() -> dict:
    config = _default_config()
    path = _config_path()
    if not path.exists():
        return config

    try:
        with open(path, "r", encoding="utf-8") as handle:
            loaded = json.load(handle)
            if isinstance(loaded, dict):
                _deep_merge(config, loaded)
    except Exception as exc:
        log.warning("Unable to load config from %s: %s", path, exc)
    return config


def _save_config(config: dict) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2)


def _get_nested_value(config: dict, path: str, default=None):
    cursor = config
    for key in path.split("."):
        if not isinstance(cursor, dict):
            return default
        cursor = cursor.get(key)
        if cursor is None:
            return default
    return cursor


def _set_nested_value(config: dict, path: str, value) -> None:
    keys = path.split(".")
    cursor = config
    for key in keys[:-1]:
        if key not in cursor or not isinstance(cursor[key], dict):
            cursor[key] = {}
        cursor = cursor[key]
    cursor[keys[-1]] = value


def _is_online() -> bool:
    try:
        with socket.create_connection(("1.1.1.1", 53), timeout=1.2):
            return True
    except OSError:
        return False


def _fetch_ollama_models(ollama_url: str) -> list[str]:
    tags_url = f"{ollama_url.rstrip('/')}/api/tags"
    try:
        with urlrequest.urlopen(tags_url, timeout=2) as response:
            if response.getcode() != 200:
                return []
            payload = json.loads(response.read().decode("utf-8"))
            models = payload.get("models", [])
            return [model.get("name") for model in models if model.get("name")]
    except (urlerror.URLError, TimeoutError, ValueError, OSError):
        return []


def _build_provider_catalog(config: dict) -> list[dict]:
    ai_config = config.get("ai", {})
    api_keys = config.get("api_keys", {})
    selected_provider = ai_config.get("default_provider", "openrouter")
    ollama_url = ai_config.get("ollama_url", "http://localhost:11434")
    live_ollama_models = _fetch_ollama_models(ollama_url)

    providers = []
    for provider_id, metadata in PROVIDER_CATALOG.items():
        models = list(metadata.get("models", []))
        enabled = True
        available = True

        if metadata.get("requires_key"):
            enabled = bool(str(api_keys.get(provider_id, "")).strip())

        if provider_id == "ollama":
            if live_ollama_models:
                models = live_ollama_models
            else:
                available = False

        providers.append(
            {
                "id": provider_id,
                "name": metadata["name"],
                "models": models,
                "requires_key": metadata.get("requires_key", False),
                "enabled": enabled,
                "available": available,
                "selected": provider_id == selected_provider,
            }
        )

    return providers


def _mission_settings_payload(config: dict) -> dict:
    current_provider = _get_nested_value(config, "ai.default_provider", "openrouter")
    return {
        "online_mode": current_provider != "ollama",
        "current_provider": current_provider,
        "current_model": _get_nested_value(config, "ai.model", ""),
        "offline_model": _get_nested_value(config, "ai.offline_model", ""),
        "ollama_url": _get_nested_value(config, "ai.ollama_url", "http://localhost:11434"),
        "personality_current": _get_nested_value(config, "personality.current", "assistant"),
        "features": {
            "enable_tts": bool(_get_nested_value(config, "features.enable_tts", True)),
            "enable_stt": bool(_get_nested_value(config, "features.enable_stt", True)),
            "enable_weather": bool(_get_nested_value(config, "features.enable_weather", True)),
            "enable_anomaly_detection": bool(
                _get_nested_value(config, "features.enable_anomaly_detection", False)
            ),
            "enable_camera": bool(_get_nested_value(config, "features.enable_camera", False)),
        },
        "wake_word_enabled": bool(_get_nested_value(config, "wake_word.enabled", True)),
    }


def _serialize_status(config: dict) -> dict:
    online = _is_online()
    provider = _get_nested_value(config, "ai.default_provider", "openrouter")
    status_payload = {
        "status": "running",
        "personality": _get_nested_value(config, "personality.current", "assistant"),
        "battery": None,
        "wifi": 4 if online else 0,
        "online": online,
        "mode_online": provider != "ollama",
        "provider": provider,
        "model": _get_nested_value(config, "ai.model", ""),
        "offline_model": _get_nested_value(config, "ai.offline_model", ""),
        "version": "0.1.0",
    }

    try:
        import psutil

        battery = psutil.sensors_battery()
        status_payload["battery"] = int(battery.percent) if battery else None
        status_payload["cpu_percent"] = psutil.cpu_percent(interval=0.0)
        status_payload["memory_percent"] = psutil.virtual_memory().percent
        status_payload["disk_percent"] = psutil.disk_usage("/").percent
        status_payload["uptime_seconds"] = int(time.time() - psutil.boot_time())
    except Exception:
        # System telemetry is best effort and should not fail status endpoint.
        pass

    return status_payload


def _key_status(config: dict) -> dict:
    keys = config.get("api_keys", {})
    return {provider: bool(str(value).strip()) for provider, value in keys.items()}


# ── Routes ─────────────────────────────────────────────────────


@app.route("/")
def index():
    """Main page - redirects to wizard or dashboard."""
    config = _load_config()
    if config.get("setup_complete", False):
        return redirect(url_for("dashboard"))
    return redirect(url_for("wizard"))


@app.route("/wizard")
def wizard():
    """Setup wizard page."""
    return render_template("wizard.html")


@app.route("/dashboard")
def dashboard():
    """Main dashboard."""
    return render_template("dashboard.html")


@app.route("/api/status")
def api_status():
    """Get MiBud status."""
    return jsonify(_serialize_status(_load_config()))


@app.route("/api/config")
def api_config():
    """Get full configuration."""
    return jsonify(_load_config())


@app.route("/api/config/save", methods=["POST"])
@require_auth
def api_config_save():
    """Save full configuration."""
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"success": False, "error": "Invalid JSON payload"}), 400

        _save_config(data)
        return jsonify({"success": True})
    except Exception as exc:
        return jsonify({"success": False, "error": getattr(exc, "message", None) or str(exc)}), 500


@app.route("/api/personality/list")
def api_personality_list():
    """Get available personalities."""
    from personalities import get_all_personalities

    personalities = get_all_personalities()
    return jsonify(
        [
            {
                "id": personality.id,
                "name": personality.name,
                "description": personality.description,
                "emoji": personality.emoji,
                "specialty": personality.specialty,
            }
            for personality in personalities
        ]
    )


@app.route("/api/personality/set", methods=["POST"])
@require_auth
def api_personality_set():
    """Set current personality."""
    data = request.get_json(silent=True) or {}
    personality = data.get("personality")

    if not personality:
        return jsonify({"success": False, "error": "No personality specified"}), 400

    config = _load_config()
    config.setdefault("personality", {})
    config["personality"]["current"] = personality
    _save_config(config)
    return jsonify({"success": True})


@app.route("/api/personality/create", methods=["POST"])
@require_auth
def api_personality_create():
    """Create a new custom personality."""
    try:
        from personalities.manager import PersonalityManager

        manager = PersonalityManager()
        personality = manager.create_personality(request.get_json(silent=True) or {})
        return jsonify(
            {
                "success": True,
                "personality": {
                    "id": personality.id,
                    "name": personality.name,
                    "description": personality.description,
                    "emoji": personality.emoji,
                },
            }
        )
    except Exception as exc:
        return jsonify({"success": False, "error": getattr(exc, "message", None) or str(exc)}), 500


@app.route("/api/personality/<personality_id>")
def api_personality_get(personality_id):
    """Get personality details."""
    from personalities.manager import PersonalityManager

    manager = PersonalityManager()
    details = manager.get_personality_details(personality_id)
    if details:
        return jsonify(details)
    return jsonify({"error": "Personality not found"}), 404


@app.route("/api/personality/<personality_id>", methods=["PUT"])
@require_auth
def api_personality_update(personality_id):
    """Update a custom personality."""
    try:
        from personalities.manager import PersonalityManager

        manager = PersonalityManager()
        personality = manager.update_personality(personality_id, request.get_json(silent=True) or {})
        if personality:
            return jsonify({"success": True})
        return jsonify({"success": False, "error": "Custom personality not found"}), 404
    except Exception as exc:
        return jsonify({"success": False, "error": getattr(exc, "message", None) or str(exc)}), 500


@app.route("/api/personality/<personality_id>", methods=["DELETE"])
@require_auth
def api_personality_delete(personality_id):
    """Delete a custom personality."""
    from personalities.manager import PersonalityManager

    manager = PersonalityManager()
    if manager.delete_personality(personality_id):
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Personality not found or is a preset"}), 404


@app.route("/api/providers")
def api_providers():
    """Get available AI providers with live status."""
    return jsonify(_build_provider_catalog(_load_config()))


def _write_keys_to_env(keys: dict) -> None:
    """Write API keys to .env file — never to config.json"""
    env_path = Path(__file__).parent.parent / ".env"
    existing = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                existing[k.strip()] = v.strip()

    for provider, key in keys.items():
        env_name = f"{provider.upper()}_API_KEY"
        existing[env_name] = key

    with open(env_path, "w") as f:
        for k, v in existing.items():
            f.write(f"{k}={v}\n")
    log.info(f"Updated {len(keys)} key(s) in .env")


@app.route("/api/keys/save", methods=["POST"])
@require_auth
def api_keys_save():
    """Save API keys to .env file"""
    data = request.get_json(silent=True) or {}
    keys = data.get("keys", {})
    if not isinstance(keys, dict):
        return jsonify({"success": False, "error": "Invalid key payload"}), 400

    try:
        _write_keys_to_env(keys)
        return jsonify({"success": True})
    except Exception as exc:
        log.error(f"Failed to write keys to .env: {exc}")
        return jsonify({"success": False, "error": getattr(exc, "message", None) or str(exc)}), 500


@app.route("/api/pin/set", methods=["POST"])
def api_pin_set():
    """Set the setup PIN and mark session as authenticated."""
    data = request.get_json(silent=True) or {}
    pin = data.get("pin", "")
    if not pin or len(pin) < 4:
        return jsonify({"error": "PIN must be at least 4 characters"}), 400
    from web.auth import set_pin as _set_pin
    _set_pin(pin)
    session["auth_ok"] = True
    return jsonify({"success": True})


@app.route("/api/mission/bootstrap")
def api_mission_bootstrap():
    """Bootstrap data for Mission CTL dashboard."""
    config = _load_config()
    try:
        from personalities import get_all_personalities

        personalities = [
            {
                "id": personality.id,
                "name": personality.name,
                "description": personality.description,
                "emoji": personality.emoji,
                "specialty": personality.specialty,
            }
            for personality in get_all_personalities()
        ]
    except Exception:
        personalities = []

    return jsonify(
        {
            "success": True,
            "status": _serialize_status(config),
            "settings": _mission_settings_payload(config),
            "providers": _build_provider_catalog(config),
            "keys": _key_status(config),
            "personalities": personalities,
        }
    )


@app.route("/api/mission/settings", methods=["POST"])
@require_auth
def api_mission_settings():
    """Update a single mission setting path."""
    data = request.get_json(silent=True) or {}
    path = data.get("path")
    value = data.get("value")
    if not path:
        return jsonify({"success": False, "error": "Missing setting path"}), 400

    config = _load_config()
    ai_config = config.setdefault("ai", {})

    if path == "mission.online_mode":
        if not isinstance(value, bool):
            return jsonify({"success": False, "error": "online_mode must be boolean"}), 400

        current_provider = ai_config.get("default_provider", "openrouter")
        if value:
            if current_provider == "ollama":
                ai_config["default_provider"] = ai_config.get("online_provider_preference", "openrouter")
        else:
            if current_provider != "ollama":
                ai_config["online_provider_preference"] = current_provider
                ai_config["default_provider"] = "ollama"
    elif path in MISSION_BOOL_PATHS:
        if not isinstance(value, bool):
            return jsonify({"success": False, "error": f"{path} must be boolean"}), 400
        _set_nested_value(config, path, value)
    elif path in MISSION_STRING_PATHS:
        if not isinstance(value, str):
            return jsonify({"success": False, "error": f"{path} must be string"}), 400
        _set_nested_value(config, path, value.strip())
    else:
        return jsonify({"success": False, "error": "Path not allowed"}), 400

    _save_config(config)
    return jsonify(
        {
            "success": True,
            "settings": _mission_settings_payload(config),
            "providers": _build_provider_catalog(config),
        }
    )


@app.route("/api/mission/provider", methods=["POST"])
@require_auth
def api_mission_provider():
    """Set active provider and model from Mission CTL."""
    data = request.get_json(silent=True) or {}
    provider = str(data.get("provider", "")).strip().lower()
    model = str(data.get("model", "")).strip()
    if provider not in PROVIDER_CATALOG:
        return jsonify({"success": False, "error": "Unknown provider"}), 400

    config = _load_config()
    ai_config = config.setdefault("ai", {})
    ai_config["default_provider"] = provider
    if provider != "ollama":
        ai_config["online_provider_preference"] = provider

    if model:
        if provider == "ollama":
            ai_config["offline_model"] = model
        else:
            ai_config["model"] = model

    _save_config(config)
    return jsonify(
        {
            "success": True,
            "settings": _mission_settings_payload(config),
            "providers": _build_provider_catalog(config),
        }
    )


# ── Wizard Steps ──────────────────────────────────────────────


@app.route("/wizard/step/<int:step>")
def wizard_step(step):
    """Get wizard step content."""
    steps = {
        1: {"title": "Welcome", "description": "Welcome to MiBud setup!"},
        2: {"title": "Hardware", "description": "Detecting hardware..."},
        3: {"title": "Audio", "description": "Testing audio..."},
        4: {"title": "WiFi", "description": "Connecting to network..."},
        5: {"title": "AI Provider", "description": "Choose your AI provider..."},
        6: {"title": "API Keys", "description": "Enter your API keys..."},
        7: {"title": "Personality", "description": "Choose your MiBud personality..."},
        8: {"title": "Complete", "description": "Setup complete!"},
    }

    if step in steps:
        return jsonify(steps[step])
    return jsonify({"error": "Invalid step"})


# ── Camera ─────────────────────────────────────────────────────


@app.route("/api/camera/capture")
def api_camera_capture():
    """Capture image from camera."""
    try:
        from hardware.camera import CameraManager
        import base64

        camera = CameraManager()
        asyncio.run(camera.initialize())
        frame = asyncio.run(camera.capture())

        if frame:
            return jsonify({"success": True, "image": base64.b64encode(frame).decode(), "format": "jpeg"})
        return jsonify({"success": False, "error": "No frame captured"})
    except Exception as exc:
        return jsonify({"success": False, "error": getattr(exc, "message", None) or str(exc)})


@app.route("/api/camera/enable", methods=["POST"])
@require_auth
def api_camera_enable():
    """Enable/disable camera feature."""
    try:
        data = request.get_json(silent=True) or {}
        enabled = bool(data.get("enabled", True))

        config = _load_config()
        config.setdefault("features", {})
        config["features"]["enable_camera"] = enabled
        _save_config(config)
        return jsonify({"success": True})
    except Exception as exc:
        return jsonify({"success": False, "error": getattr(exc, "message", None) or str(exc)})


# ── System Info ────────────────────────────────────────────────


@app.route("/api/system/info")
def api_system_info():
    """Get system information."""
    import platform
    import psutil

    try:
        battery = psutil.sensors_battery()
        return jsonify(
            {
                "platform": platform.system(),
                "machine": platform.machine(),
                "hostname": platform.node(),
                "cpu_percent": psutil.cpu_percent(interval=0.0),
                "memory_percent": psutil.virtual_memory().percent,
                "disk_percent": psutil.disk_usage("/").percent,
                "battery": int(battery.percent) if battery else None,
                "battery_charging": bool(battery.power_plugged) if battery else None,
                "cpu_temp": None,
            }
        )
    except Exception as exc:
        return jsonify({"error": getattr(exc, "message", None) or type(exc).__name__}), 500


@app.route("/api/system/stats")
def api_system_stats():
    """Get system statistics."""
    import psutil

    try:
        net = psutil.net_io_counters()
        disk = psutil.disk_io_counters()
        return jsonify(
            {
                "cpu_percent": psutil.cpu_percent(interval=0.0),
                "memory_percent": psutil.virtual_memory().percent,
                "network_bytes_sent": net.bytes_sent if net else 0,
                "network_bytes_recv": net.bytes_recv if net else 0,
                "disk_io": {
                    "read_count": disk.read_count if disk else 0,
                    "write_count": disk.write_count if disk else 0,
                },
            }
        )
    except Exception as exc:
        return jsonify({"error": getattr(exc, "message", None) or type(exc).__name__}), 500


# ── Alerts ─────────────────────────────────────────────────────


@app.route("/api/alerts")
def api_alerts():
    """Get recent alerts."""
    from ai.anomaly import AnomalyDetector

    try:
        detector = AnomalyDetector()
        alerts = detector.get_alert_history()
        return jsonify({"alerts": alerts})
    except Exception as exc:
        return jsonify({"alerts": [], "error": getattr(exc, "message", None) or type(exc).__name__})


@app.route("/api/alerts/clear", methods=["POST"])
@require_auth
def api_alerts_clear():
    """Clear alert history."""
    from ai.anomaly import AnomalyDetector

    try:
        detector = AnomalyDetector()
        detector.clear_alerts()
        return jsonify({"success": True})
    except Exception as exc:
        return jsonify({"success": False, "error": getattr(exc, "message", None) or str(exc)})


# ── Main ───────────────────────────────────────────────────────


def run_server(host="0.0.0.0", port=5000):
    """Run the web server."""
    log.info("🌐 Starting web server at http://%s:%s", host, port)
    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    run_server()
