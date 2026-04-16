"""
web/auth.py — PIN gate for Flask web API
"""
import hashlib
import secrets
from pathlib import Path
from functools import wraps

from flask import request, jsonify, session

log = __import__("logging").getLogger("MiBud")

_PIN_DIR = Path(__file__).parent.parent / "config"
_PIN_DIR.mkdir(parents=True, exist_ok=True)
_PIN_HASH_FILE = _PIN_DIR / ".pin_hash"


def _hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.encode()).hexdigest()


def _verify_pin(pin: str) -> bool:
    if not _PIN_HASH_FILE.exists():
        return False
    stored = _PIN_HASH_FILE.read_text().strip()
    if not stored:
        return False
    return secrets.compare_digest(_hash_pin(pin), stored)


def set_pin(pin: str) -> None:
    """Set the setup PIN. Call this from the wizard."""
    _PIN_HASH_FILE.write_text(_hash_pin(pin))


def has_pin() -> bool:
    return _PIN_HASH_FILE.exists() and _PIN_HASH_FILE.read_text().strip()


def require_auth(f):
    """Decorator: require valid PIN session for API endpoints."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get("auth_ok"):
            return f(*args, **kwargs)
        pin = request.headers.get("X-MiBud-PIN") or request.args.get("pin")
        if pin and _verify_pin(pin):
            session["auth_ok"] = True
            return f(*args, **kwargs)
        return jsonify({"error": "Unauthorized — set PIN or provide X-MiBud-PIN header"}), 401
    return decorated
