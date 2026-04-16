"""
tests/test_web_errors.py
Flask API must return clean error responses — no stack traces or file paths to clients
"""
import pytest


def test_api_errors_return_clean_json_no_traceback(app_with_test_env):
    """API errors must return clean JSON — no stack traces"""
    resp = app_with_test_env.get("/api/config/save")  # GET not allowed on POST endpoint
    # Should return 405 Method Not Allowed or clean error
    data = resp.get_json() or {}
    body_str = str(data).lower()
    assert "traceback" not in body_str, f"Traceback leaked: {data}"
    assert "file " not in body_str, f"File path leaked: {data}"


def test_api_status_error_is_clean(app_with_test_env):
    """api_status should never leak internal errors"""
    # Patch _serialize_status to raise
    import web.server
    orig = web.server._serialize_status

    def bad_status(cfg):
        raise RuntimeError("/fake/path/to/module.py:42")

    web.server._serialize_status = bad_status
    try:
        resp = app_with_test_env.get("/api/status")
        data = resp.get_json() or {}
        body_str = str(data).lower()
        assert "traceback" not in body_str
        assert "/fake/path" not in body_str
        assert "module.py" not in body_str
    finally:
        web.server._serialize_status = orig
