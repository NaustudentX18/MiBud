"""
MiBud Web API v2

New endpoints for:
- Long-term memory (inspect, search, delete, wipe, profile)
- Tool registry (list, invoke)
- Power profiles (snapshot, set, auto)
- Provider health (circuit breaker state, switch)
- SSE streaming chat (/api/chat/stream)

Uses a lightweight service locator so endpoints don't import core.main.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass
from typing import Any, Optional

from flask import Blueprint, Response, jsonify, request, stream_with_context

from web.auth import require_auth

log = logging.getLogger("MiBud")


@dataclass
class ServiceLocator:
    """Thin handle so web routes can reach the running MiBud subsystems.

    Populated by `bind_services()` once the main app has booted.
    """
    memory: Any = None
    conversation: Any = None
    ai_router: Any = None
    power_manager: Any = None
    tool_registry: Any = None
    # v3 additions
    trace_log: Any = None
    backup_manager: Any = None
    plugin_loader: Any = None
    mcp_manager: Any = None
    dialog_session: Any = None


_services = ServiceLocator()


def bind_services(**kwargs) -> None:
    """Wire live subsystems into the API (called from core.main once up)."""
    for k, v in kwargs.items():
        if hasattr(_services, k):
            setattr(_services, k, v)


api_v2 = Blueprint("api_v2", __name__)


# ---------------------------------------------------------------------------
# Async bridge — the Flask dev server is sync; the AI stack is async.
# We run a single background event loop on a dedicated thread and submit
# coroutines to it from handlers.
# ---------------------------------------------------------------------------


class _AsyncBridge:
    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def _ensure(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is not None and self._loop.is_running():
                return self._loop
            self._loop = asyncio.new_event_loop()

            def _run(loop):
                asyncio.set_event_loop(loop)
                loop.run_forever()

            self._thread = threading.Thread(target=_run, args=(self._loop,), daemon=True)
            self._thread.start()
            return self._loop

    def run(self, coro, timeout: float = 30.0):
        loop = self._ensure()
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        return fut.result(timeout=timeout)

    def stream(self, coro_factory):
        """Drive an async generator from a sync iterator."""
        loop = self._ensure()
        q: asyncio.Queue = asyncio.Queue()
        SENTINEL = object()

        async def _pump():
            try:
                async for item in coro_factory():
                    await q.put(item)
            except Exception as e:  # pragma: no cover
                await q.put(("__err__", str(e)))
            finally:
                await q.put(SENTINEL)

        asyncio.run_coroutine_threadsafe(_pump(), loop)

        while True:
            fut = asyncio.run_coroutine_threadsafe(q.get(), loop)
            item = fut.result()
            if item is SENTINEL:
                return
            if isinstance(item, tuple) and item and item[0] == "__err__":
                yield {"event": "error", "data": item[1]}
                return
            yield {"event": "token", "data": item}


_bridge = _AsyncBridge()


# ---------------------------------------------------------------------------
# Memory endpoints
# ---------------------------------------------------------------------------


@api_v2.route("/api/memory/stats", methods=["GET"])
@require_auth
def memory_stats():
    m = _services.memory
    if m is None:
        return jsonify({"success": False, "error": "memory not available"}), 503
    return jsonify({"success": True, "stats": m.stats(), "session_id": m.session_id})


@api_v2.route("/api/memory/facts", methods=["GET"])
@require_auth
def memory_facts():
    m = _services.memory
    if m is None:
        return jsonify({"success": False, "error": "memory not available"}), 503
    category = request.args.get("category") or None
    limit = int(request.args.get("limit", "200"))
    facts = m.list_facts(category=category, limit=limit)
    return jsonify({
        "success": True,
        "count": len(facts),
        "facts": [f.__dict__ for f in facts],
    })


@api_v2.route("/api/memory/search", methods=["GET", "POST"])
@require_auth
def memory_search():
    m = _services.memory
    if m is None:
        return jsonify({"success": False, "error": "memory not available"}), 503
    payload = request.get_json(silent=True) or {}
    query = payload.get("query") or request.args.get("query", "")
    k = int(payload.get("k", request.args.get("k", 5)))
    if not query:
        return jsonify({"success": False, "error": "query is required"}), 400
    hits = _bridge.run(m.recall(query, k=k))
    return jsonify({"success": True, "query": query, "hits": [h.__dict__ for h in hits]})


@api_v2.route("/api/memory/fact", methods=["POST"])
@require_auth
def memory_add_fact():
    m = _services.memory
    if m is None:
        return jsonify({"success": False, "error": "memory not available"}), 503
    payload = request.get_json(silent=True) or {}
    fact = (payload.get("fact") or "").strip()
    if not fact:
        return jsonify({"success": False, "error": "fact is required"}), 400
    fid = _bridge.run(m.remember_fact(
        fact,
        category=payload.get("category", "general"),
        confidence=float(payload.get("confidence", 0.9)),
    ))
    return jsonify({"success": True, "fact_id": fid})


@api_v2.route("/api/memory/fact/<fact_id>", methods=["DELETE"])
@require_auth
def memory_delete_fact(fact_id: str):
    m = _services.memory
    if m is None:
        return jsonify({"success": False, "error": "memory not available"}), 503
    ok = m.delete_fact(fact_id)
    return jsonify({"success": ok})


@api_v2.route("/api/memory/profile", methods=["GET", "POST"])
@require_auth
def memory_profile():
    m = _services.memory
    if m is None:
        return jsonify({"success": False, "error": "memory not available"}), 503
    if request.method == "GET":
        return jsonify({"success": True, "profile": m.all_profile()})
    payload = request.get_json(silent=True) or {}
    for k, v in payload.items():
        m.set_profile(k, v)
    return jsonify({"success": True, "profile": m.all_profile()})


@api_v2.route("/api/memory/sessions", methods=["GET"])
@require_auth
def memory_sessions():
    m = _services.memory
    if m is None:
        return jsonify({"success": False, "error": "memory not available"}), 503
    limit = int(request.args.get("limit", "10"))
    return jsonify({"success": True, "sessions": m.list_recent_sessions(limit=limit)})


@api_v2.route("/api/memory/wipe", methods=["POST"])
@require_auth
def memory_wipe():
    m = _services.memory
    if m is None:
        return jsonify({"success": False, "error": "memory not available"}), 503
    payload = request.get_json(silent=True) or {}
    if payload.get("confirm") != "WIPE":
        return jsonify({"success": False, "error": "send {\"confirm\": \"WIPE\"} to confirm"}), 400
    m.clear_all()
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Tool endpoints
# ---------------------------------------------------------------------------


def _active_registry():
    reg = _services.tool_registry
    if reg is None:
        from ai.tools import get_registry
        reg = get_registry()
    return reg


@api_v2.route("/api/tools/list", methods=["GET"])
@require_auth
def tools_list():
    reg = _active_registry()
    out = []
    for spec in reg.all():
        out.append({
            "name": spec.name,
            "description": spec.description,
            "category": spec.category,
            "side_effects": spec.side_effects,
            "params": [p.__dict__ for p in spec.params],
        })
    return jsonify({"success": True, "tools": out})


@api_v2.route("/api/tools/invoke", methods=["POST"])
@require_auth
def tools_invoke():
    payload = request.get_json(silent=True) or {}
    name = payload.get("name")
    args = payload.get("args") or {}
    if not name:
        return jsonify({"success": False, "error": "name is required"}), 400
    reg = _active_registry()
    result = _bridge.run(reg.invoke(name, args))
    return jsonify({"success": bool(result.get("ok")), "result": result})


# ---------------------------------------------------------------------------
# Power profile endpoints
# ---------------------------------------------------------------------------


@api_v2.route("/api/power/status", methods=["GET"])
@require_auth
def power_status():
    pm = _services.power_manager
    if pm is None:
        return jsonify({"success": False, "error": "power manager not available"}), 503
    return jsonify({"success": True, **pm.snapshot()})


@api_v2.route("/api/power/profile", methods=["POST"])
@require_auth
def power_set_profile():
    pm = _services.power_manager
    if pm is None:
        return jsonify({"success": False, "error": "power manager not available"}), 503
    payload = request.get_json(silent=True) or {}
    mode = payload.get("profile", "").lower()
    if mode == "auto":
        pm.set_auto()
    else:
        from core.power import PowerProfile
        try:
            pm.set_manual(PowerProfile(mode))
        except ValueError:
            return jsonify({"success": False, "error": f"unknown profile '{mode}'"}), 400
    return jsonify({"success": True, **pm.snapshot()})


# ---------------------------------------------------------------------------
# Provider health
# ---------------------------------------------------------------------------


@api_v2.route("/api/providers/health", methods=["GET"])
@require_auth
def providers_health():
    r = _services.ai_router
    if r is None:
        return jsonify({"success": False, "error": "router not ready"}), 503
    return jsonify({"success": True, "health": r.provider_health()})


@api_v2.route("/api/health", methods=["GET"])
def unified_health():
    """Unified health check — no auth so watchdogs / uptime bots can hit it."""
    out = {"ok": True, "subsystems": {}}
    if _services.ai_router is not None:
        out["subsystems"]["ai_router"] = {
            "initialized": getattr(_services.ai_router, "is_initialized", False),
            "providers": list(getattr(_services.ai_router, "_providers", {}).keys()),
        }
    if _services.memory is not None:
        try:
            out["subsystems"]["memory"] = _services.memory.stats()
        except Exception as e:
            out["subsystems"]["memory"] = {"error": str(e)}
    if _services.power_manager is not None:
        try:
            out["subsystems"]["power"] = _services.power_manager.snapshot()
        except Exception as e:
            out["subsystems"]["power"] = {"error": str(e)}
    if _services.tool_registry is not None:
        try:
            out["subsystems"]["tools"] = {"count": len(_services.tool_registry.names())}
        except Exception:
            pass
    if _services.trace_log is not None:
        try:
            out["subsystems"]["trace"] = _services.trace_log.stats()
        except Exception:
            pass
    if _services.mcp_manager is not None:
        try:
            out["subsystems"]["mcp"] = {
                "servers": len(_services.mcp_manager.servers),
            }
        except Exception:
            pass
    if _services.plugin_loader is not None:
        try:
            plugins = _services.plugin_loader.loaded
            out["subsystems"]["plugins"] = {
                "loaded": sum(1 for p in plugins.values() if p.ok),
                "total": len(plugins),
            }
        except Exception:
            pass
    return jsonify(out)


# ---------------------------------------------------------------------------
# Streaming chat (Server-Sent Events)
# ---------------------------------------------------------------------------


@api_v2.route("/api/chat/stream", methods=["POST"])
@require_auth
def chat_stream():
    """SSE stream of assistant tokens.

    Body: {"prompt": "...", "context": [...], "prefer_offline": false}
    Output: lines of `data: {json}` terminated by `data: [DONE]`.
    """
    router = _services.ai_router
    if router is None:
        return jsonify({"success": False, "error": "router not ready"}), 503

    payload = request.get_json(silent=True) or {}
    prompt = payload.get("prompt", "").strip()
    if not prompt:
        return jsonify({"success": False, "error": "prompt is required"}), 400

    from ai.router import ChatMessage
    context = [
        ChatMessage(role=m.get("role", "user"), content=m.get("content", ""))
        for m in (payload.get("context") or [])
        if isinstance(m, dict)
    ]
    prefer_offline = bool(payload.get("prefer_offline", False))

    def factory():
        return router.generate_stream(
            prompt=prompt, context=context, prefer_offline=prefer_offline,
        )

    @stream_with_context
    def _iter():
        for evt in _bridge.stream(factory):
            payload = json.dumps({"type": evt["event"], "content": evt.get("data", "")})
            yield f"data: {payload}\n\n"
        yield "data: [DONE]\n\n"

    return Response(_iter(), mimetype="text/event-stream")


# ---------------------------------------------------------------------------
# v3 endpoints — trace, backup, plugins, mcp, dialog
# ---------------------------------------------------------------------------


@api_v2.route("/api/v3/trace", methods=["GET"])
@require_auth
def v3_trace():
    """Return the tail of the conversation trace log.

    Query params: ?limit=50 (default 50, max 500).
    """
    tl = _services.trace_log
    if tl is None:
        return jsonify({"success": False, "error": "trace not available"}), 503
    try:
        limit = max(1, min(int(request.args.get("limit", "50")), 500))
    except (TypeError, ValueError):
        limit = 50
    return jsonify({
        "success": True,
        "stats": tl.stats(),
        "entries": tl.recent(limit=limit),
    })


@api_v2.route("/api/v3/backup", methods=["POST"])
@require_auth
def v3_backup_create():
    """Export a tar.gz backup. Body: {"path": "optional/abs/path"}."""
    bm = _services.backup_manager
    if bm is None:
        return jsonify({"success": False, "error": "backup not available"}), 503
    payload = request.get_json(silent=True) or {}
    import time as _time
    from pathlib import Path as _Path
    default_name = f"mibud-backup-{int(_time.time())}.tar.gz"
    dest = _Path(payload.get("path") or ("data/backups/" + default_name))
    try:
        info = bm.export(dest)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    return jsonify({"success": True, "backup": info.__dict__})


@api_v2.route("/api/v3/backup/restore", methods=["POST"])
@require_auth
def v3_backup_restore():
    """Restore from an existing backup.

    Body: {"path": "/abs/path/to/backup.tar.gz", "force": false}.
    A running instance won't reload live state — callers should restart the
    service after a successful restore.
    """
    bm = _services.backup_manager
    if bm is None:
        return jsonify({"success": False, "error": "backup not available"}), 503
    payload = request.get_json(silent=True) or {}
    path = payload.get("path")
    if not path:
        return jsonify({"success": False, "error": "path is required"}), 400
    force = bool(payload.get("force", False))
    try:
        manifest = bm.restore(path, force=force)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400
    return jsonify({
        "success": True,
        "manifest": manifest,
        "note": "restart the service to reload restored state",
    })


@api_v2.route("/api/v3/backup/inspect", methods=["GET"])
@require_auth
def v3_backup_inspect():
    bm = _services.backup_manager
    if bm is None:
        return jsonify({"success": False, "error": "backup not available"}), 503
    path = request.args.get("path")
    if not path:
        return jsonify({"success": False, "error": "path is required"}), 400
    try:
        manifest = bm.inspect(path)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 400
    return jsonify({"success": True, "manifest": manifest})


@api_v2.route("/api/v3/plugins", methods=["GET"])
@require_auth
def v3_plugins_list():
    pl = _services.plugin_loader
    if pl is None:
        return jsonify({"success": False, "error": "plugins not available"}), 503
    return jsonify({
        "success": True,
        "plugins": [p.__dict__ for p in pl.loaded.values()],
    })


@api_v2.route("/api/v3/plugins/reload", methods=["POST"])
@require_auth
def v3_plugins_reload():
    pl = _services.plugin_loader
    if pl is None:
        return jsonify({"success": False, "error": "plugins not available"}), 503
    results = pl.load_all()
    return jsonify({"success": True, "plugins": [p.__dict__ for p in results]})


@api_v2.route("/api/v3/mcp", methods=["GET"])
@require_auth
def v3_mcp_status():
    mm = _services.mcp_manager
    if mm is None:
        return jsonify({"success": False, "error": "mcp not available"}), 503
    return jsonify({"success": True, "servers": mm.status()})


@api_v2.route("/api/v3/dialog", methods=["GET"])
@require_auth
def v3_dialog_status():
    ds = _services.dialog_session
    if ds is None:
        return jsonify({"success": False, "error": "dialog not available"}), 503
    return jsonify({
        "success": True,
        "state": ds.state.value,
        "continuous": ds.continuous,
        "stats": ds.stats(),
    })


@api_v2.route("/api/v3/dialog/continuous", methods=["POST"])
@require_auth
def v3_dialog_continuous():
    ds = _services.dialog_session
    if ds is None:
        return jsonify({"success": False, "error": "dialog not available"}), 503
    payload = request.get_json(silent=True) or {}
    ds.set_continuous(bool(payload.get("enabled", True)))
    return jsonify({"success": True, "continuous": ds.continuous})


def register_v2(app) -> None:
    """Register the v2 blueprint on `app`."""
    app.register_blueprint(api_v2)
