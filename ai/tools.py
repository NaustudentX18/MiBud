"""
MiBud AI - Tool Use / Function Calling

A provider-agnostic tool registry that lets the LLM actually *do* things:
set timers, take photos, read the battery, search its own memory, trigger
Home Assistant, and so on.

Design goals:
- Zero boilerplate: decorate a function and it becomes a tool.
- Providers: one `ToolSpec` gets adapted to OpenAI / Anthropic / Google
  / OpenRouter function-call formats.
- Safe: every invocation is sandboxed with a timeout and structured errors.
- Async-first but accepts sync callables transparently.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
import typing
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

log = logging.getLogger("MiBud")

ToolFunc = Callable[..., Union[Any, Awaitable[Any]]]


# ---------------------------------------------------------------------------
# Schema + registry
# ---------------------------------------------------------------------------

_PY_TO_JSON = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}

_NAME_TO_JSON = {
    "str": "string", "int": "integer", "float": "number", "bool": "boolean",
    "list": "array", "List": "array", "tuple": "array", "Tuple": "array",
    "dict": "object", "Dict": "object", "Any": "string", "None": "string",
    "Optional": "string",
}


def _annotation_to_json(ann: Any) -> str:
    """Resolve a python annotation (class or PEP-563 string) to a JSON-schema type."""
    if ann is inspect._empty:
        return "string"
    if isinstance(ann, str):
        # PEP 563: annotations are strings under `from __future__ import annotations`.
        # Strip subscripts like `List[int]` -> `List`, `Optional[str]` -> `Optional`.
        stripped = ann.split("[", 1)[0].strip()
        return _NAME_TO_JSON.get(stripped, "string")
    origin = getattr(ann, "__origin__", None)
    if origin is not None and origin in _PY_TO_JSON:
        return _PY_TO_JSON[origin]
    return _PY_TO_JSON.get(ann, "string")


@dataclass
class ToolParam:
    name: str
    type: str = "string"
    description: str = ""
    required: bool = True
    enum: Optional[List[Any]] = None


@dataclass
class ToolSpec:
    name: str
    description: str
    params: List[ToolParam] = field(default_factory=list)
    func: Optional[ToolFunc] = None
    category: str = "general"
    side_effects: bool = False  # True for state-changing tools

    def to_json_schema(self) -> Dict[str, Any]:
        """Return JSON-schema properties for the parameters."""
        props: Dict[str, Any] = {}
        required: List[str] = []
        for p in self.params:
            entry: Dict[str, Any] = {"type": p.type, "description": p.description}
            if p.enum is not None:
                entry["enum"] = p.enum
            props[p.name] = entry
            if p.required:
                required.append(p.name)
        return {"type": "object", "properties": props, "required": required}

    def to_openai(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.to_json_schema(),
            },
        }

    def to_anthropic(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.to_json_schema(),
        }

    def to_google(self) -> Dict[str, Any]:
        schema = self.to_json_schema()
        # Gemini uses OpenAPI-ish types in uppercase
        def _upcase(s):
            if isinstance(s, dict):
                out = {}
                for k, v in s.items():
                    if k == "type" and isinstance(v, str):
                        out[k] = v.upper()
                    else:
                        out[k] = _upcase(v)
                return out
            return s
        return {
            "name": self.name,
            "description": self.description,
            "parameters": _upcase(schema),
        }


class ToolRegistry:
    """Global registry; can be scoped by category."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> ToolSpec:
        if spec.name in self._tools:
            log.debug(f"🛠️  Overwriting tool '{spec.name}'")
        self._tools[spec.name] = spec
        return spec

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def all(self, category: Optional[str] = None) -> List[ToolSpec]:
        if category is None:
            return list(self._tools.values())
        return [t for t in self._tools.values() if t.category == category]

    def names(self) -> List[str]:
        return sorted(self._tools)

    async def invoke(self, name: str, args: Dict[str, Any], timeout: float = 15.0) -> Dict[str, Any]:
        """Invoke a tool with structured result.

        Returns `{"ok": bool, "result": ..., "error": str|None, "tool": name}`.
        """
        spec = self._tools.get(name)
        if spec is None or spec.func is None:
            return {"ok": False, "tool": name, "error": f"unknown tool '{name}'"}

        # Filter args to the declared params so the model can't slip extras.
        allowed = {p.name for p in spec.params}
        safe_args = {k: v for k, v in args.items() if k in allowed}

        try:
            result = spec.func(**safe_args)
            if inspect.isawaitable(result):
                result = await asyncio.wait_for(result, timeout=timeout)
        except asyncio.TimeoutError:
            return {"ok": False, "tool": name, "error": f"timeout after {timeout}s"}
        except TypeError as e:
            return {"ok": False, "tool": name, "error": f"bad arguments: {e}"}
        except Exception as e:
            log.exception(f"🛠️  Tool '{name}' failed")
            return {"ok": False, "tool": name, "error": str(e)}

        # Coerce non-JSON types to a serialisable summary.
        try:
            json.dumps(result)
            payload = result
        except (TypeError, ValueError):
            payload = repr(result)

        return {"ok": True, "tool": name, "result": payload}


_GLOBAL_REGISTRY = ToolRegistry()


def get_registry() -> ToolRegistry:
    return _GLOBAL_REGISTRY


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------

_DOC_PARAM_RE = re.compile(r"^\s*(?:-|\*)?\s*(\w+)\s*(?:\(([^)]+)\))?\s*:\s*(.+)$")


def _parse_docstring(doc: Optional[str]) -> (str, Dict[str, str]):
    """Split a docstring into (description, {param_name: description}).

    Supports plain form:

        One-line description.

        param_name: what it is
        other: what it is
    """
    if not doc:
        return "", {}
    lines = [l.strip() for l in doc.strip().splitlines()]
    description_lines: List[str] = []
    params: Dict[str, str] = {}
    in_params = False
    for line in lines:
        if not line:
            in_params = True if description_lines else in_params
            continue
        m = _DOC_PARAM_RE.match(line) if in_params else None
        if m:
            params[m.group(1)] = m.group(3).strip()
        else:
            description_lines.append(line)
    return " ".join(description_lines).strip(), params


def tool(
    name: Optional[str] = None,
    *,
    description: Optional[str] = None,
    category: str = "general",
    side_effects: bool = False,
    enums: Optional[Dict[str, List[Any]]] = None,
    registry: Optional[ToolRegistry] = None,
) -> Callable[[ToolFunc], ToolFunc]:
    """Decorate a function as a tool.

    Parameter types come from annotations; descriptions from the docstring.
    Use the `enums` kwarg to pin specific argument to a value set.
    """

    enums = enums or {}
    reg = registry or _GLOBAL_REGISTRY

    def decorate(fn: ToolFunc) -> ToolFunc:
        sig = inspect.signature(fn)
        doc_desc, doc_params = _parse_docstring(fn.__doc__)
        # Resolve forward-ref / string annotations (PEP 563) when possible.
        try:
            hints = typing.get_type_hints(fn)
        except Exception:
            hints = {}
        params: List[ToolParam] = []
        for pname, param in sig.parameters.items():
            if pname in {"self", "cls"}:
                continue
            ann = hints.get(pname, param.annotation)
            json_t = _annotation_to_json(ann)
            params.append(
                ToolParam(
                    name=pname,
                    type=json_t,
                    description=doc_params.get(pname, ""),
                    required=param.default is inspect._empty,
                    enum=enums.get(pname),
                )
            )
        spec = ToolSpec(
            name=name or fn.__name__,
            description=description or doc_desc or fn.__name__,
            params=params,
            func=fn,
            category=category,
            side_effects=side_effects,
        )
        reg.register(spec)
        fn._tool_spec = spec  # type: ignore[attr-defined]
        return fn

    return decorate


# ---------------------------------------------------------------------------
# Built-in tool library
# ---------------------------------------------------------------------------
# A `ToolContext` is a lightweight handle to MiBud subsystems that tools need.
# Tools capture it via closure when bound.
# ---------------------------------------------------------------------------


@dataclass
class ToolContext:
    config: Any = None
    battery: Any = None
    camera: Any = None
    audio: Any = None
    display: Any = None
    led: Any = None
    buttons: Any = None
    ai_router: Any = None
    memory: Any = None
    timer_manager: Any = None
    reminder_manager: Any = None
    note_manager: Any = None
    home_automation: Any = None
    conversation: Any = None
    personality_manager: Any = None


def build_builtin_tools(ctx: ToolContext, registry: Optional[ToolRegistry] = None) -> ToolRegistry:
    """Register the standard MiBud tool set against `registry` (default: global)."""

    reg = registry or _GLOBAL_REGISTRY

    # ---- Clock / system ------------------------------------------------

    @tool(category="clock", registry=reg)
    def get_time() -> dict:
        """Return the current local date and time."""
        from datetime import datetime
        now = datetime.now()
        return {
            "iso": now.isoformat(timespec="seconds"),
            "human": now.strftime("%A %B %d, %Y at %I:%M %p"),
        }

    @tool(category="system", registry=reg)
    def get_system_info() -> dict:
        """Return CPU temperature, RAM, uptime, and disk usage."""
        from utils.utilities import SystemInfo
        return {
            "uptime": SystemInfo.get_uptime(),
            "memory": SystemInfo.get_memory_usage(),
            "cpu_temp_c": SystemInfo.get_cpu_temp(),
            "disk": SystemInfo.get_disk_usage(),
        }

    # ---- Battery --------------------------------------------------------

    @tool(category="power", registry=reg)
    def get_battery() -> dict:
        """Return battery percentage, voltage, and charging state."""
        if ctx.battery is None:
            return {"error": "battery not available"}
        s = ctx.battery.get_status()
        return {
            "level_percent": s.level,
            "voltage": round(s.voltage, 2),
            "charging": s.charging,
            "low": s.low_battery,
            "critical": s.critical,
        }

    # ---- Timers / reminders / notes ------------------------------------

    @tool(category="timer", side_effects=True, registry=reg)
    def set_timer(name: str, seconds: int) -> dict:
        """Start a timer that announces itself when it finishes.

        name: short label for the timer, e.g. 'tea' or 'laundry'
        seconds: duration in seconds
        """
        if ctx.timer_manager is None:
            return {"error": "timer manager not available"}
        tid = ctx.timer_manager.create_timer(name, int(seconds))
        return {"timer_id": tid, "name": name, "seconds": int(seconds)}

    @tool(category="timer", registry=reg)
    def list_timers() -> list:
        """List active timers and remaining seconds."""
        if ctx.timer_manager is None:
            return []
        out = []
        for t in ctx.timer_manager.get_active_timers():
            out.append({
                "id": t.id,
                "name": t.name,
                "remaining_seconds": ctx.timer_manager.get_remaining(t.id),
            })
        return out

    @tool(category="timer", side_effects=True, registry=reg)
    def cancel_timer(timer_id: str) -> dict:
        """Cancel an active timer by id."""
        if ctx.timer_manager is None:
            return {"error": "timer manager not available"}
        ok = ctx.timer_manager.cancel_timer(timer_id)
        return {"cancelled": ok, "timer_id": timer_id}

    @tool(category="reminder", side_effects=True, registry=reg)
    def create_reminder(message: str, minutes_from_now: int) -> dict:
        """Schedule a spoken reminder for later today.

        message: what to say
        minutes_from_now: how many minutes from now to fire
        """
        if ctx.reminder_manager is None:
            return {"error": "reminder manager not available"}
        rid = ctx.reminder_manager.create_reminder_relative(message, int(minutes_from_now))
        return {"reminder_id": rid, "message": message, "minutes_from_now": int(minutes_from_now)}

    @tool(category="reminder", registry=reg)
    def list_reminders(limit: int = 5) -> list:
        """List upcoming reminders in order.

        limit: max entries to return
        """
        if ctx.reminder_manager is None:
            return []
        from datetime import datetime
        out = []
        for r in ctx.reminder_manager.get_upcoming_reminders(limit=int(limit)):
            delta = (r.trigger_time - datetime.now()).total_seconds() / 60
            out.append({
                "id": r.id,
                "message": r.message,
                "in_minutes": round(delta, 1),
                "trigger_time": r.trigger_time.isoformat(),
            })
        return out

    @tool(category="notes", side_effects=True, registry=reg)
    def add_note(content: str, tags: str = "") -> dict:
        """Save a quick note.

        content: the note body
        tags: optional comma-separated tags
        """
        if ctx.note_manager is None:
            return {"error": "note manager not available"}
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        nid = ctx.note_manager.create_note(content, tag_list)
        return {"note_id": nid}

    @tool(category="notes", registry=reg)
    def search_notes(query: str) -> list:
        """Search notes by content or tag.

        query: search string (case-insensitive)
        """
        if ctx.note_manager is None:
            return []
        return [
            {"id": n.id, "content": n.content, "tags": n.tags, "created_at": n.created_at.isoformat()}
            for n in ctx.note_manager.search_notes(query)[:20]
        ]

    # ---- Long-term memory ---------------------------------------------

    @tool(category="memory", side_effects=True, registry=reg)
    def remember(fact: str, category: str = "general", confidence: float = 0.9) -> dict:
        """Store a durable fact about the user or the world.

        Use this when the user shares something you should remember next time,
        e.g. their name, preferences, routines, or goals.

        fact: the fact in one short sentence
        category: profile, preference, routine, goal, general
        confidence: 0.0-1.0 how sure you are
        """
        if ctx.memory is None:
            return {"error": "memory not available"}
        fid = ctx.memory.remember_fact(fact, category=category, confidence=float(confidence))
        return {"fact_id": fid, "stored": fact}

    @tool(category="memory", registry=reg)
    def recall(query: str, k: int = 5) -> list:
        """Search long-term memory for facts relevant to a query.

        query: natural-language question
        k: max facts to return
        """
        if ctx.memory is None:
            return []
        hits = ctx.memory.recall(query, k=int(k))
        return [
            {"fact": h.fact, "category": h.category, "score": round(h.score, 3), "created_at": h.created_at}
            for h in hits
        ]

    @tool(category="memory", registry=reg)
    def list_recent_conversations(limit: int = 3) -> list:
        """Return summaries of recent conversations.

        limit: number of sessions
        """
        if ctx.memory is None:
            return []
        return ctx.memory.list_recent_sessions(limit=int(limit))

    # ---- Vision -------------------------------------------------------

    @tool(category="vision", registry=reg)
    async def describe_scene(prompt: str = "Describe what you see in one sentence.") -> dict:
        """Take a photo and describe what's in front of the camera.

        prompt: the question to ask about the image
        """
        if ctx.camera is None or ctx.ai_router is None:
            return {"error": "camera or AI router not available"}
        try:
            image = await _maybe_await(ctx.camera.capture_bytes())
        except Exception as e:
            return {"error": f"capture failed: {e}"}
        if not image:
            return {"error": "capture returned no data"}
        r = await ctx.ai_router.generate_with_vision(prompt, image)
        return {"description": r.text, "provider": r.provider}

    # ---- Personality / system --------------------------------------------

    @tool(category="personality", side_effects=True, registry=reg)
    async def set_personality(personality_id: str) -> dict:
        """Switch MiBud to a different personality.

        personality_id: one of the registered personality ids (e.g. 'chef', 'assistant')
        """
        if ctx.conversation is None:
            return {"error": "conversation manager not available"}
        await ctx.conversation.change_personality(personality_id)
        return {"active_personality": personality_id}

    @tool(category="personality", registry=reg)
    def list_personalities() -> list:
        """List every available personality and its short description."""
        try:
            from personalities.presets import PERSONALITIES
            return [
                {"id": pid, "name": p.name, "description": getattr(p, "description", "")}
                for pid, p in PERSONALITIES.items()
            ]
        except Exception as e:
            return [{"error": str(e)}]

    # ---- Home automation -----------------------------------------------

    @tool(category="home", side_effects=True, registry=reg)
    async def home_assistant_call(domain: str, service: str, entity_id: str = "") -> dict:
        """Call a Home Assistant service, e.g. turn on a light.

        domain: HA domain like 'light' or 'switch'
        service: service name like 'turn_on', 'turn_off', 'toggle'
        entity_id: the entity, e.g. 'light.kitchen'
        """
        if ctx.home_automation is None:
            return {"error": "home assistant integration not available"}
        try:
            fn = getattr(ctx.home_automation, "call_service", None)
            if fn is None:
                return {"error": "home automation backend has no call_service"}
            res = fn(domain, service, entity_id)
            if inspect.isawaitable(res):
                res = await res
            return {"ok": True, "response": res}
        except Exception as e:
            return {"error": str(e)}

    @tool(category="home", side_effects=True, registry=reg)
    def gpio_set(pin: int, value: bool) -> dict:
        """Drive a GPIO pin HIGH or LOW.

        pin: BCM pin number
        value: True for HIGH, False for LOW
        """
        if ctx.home_automation is None:
            return {"error": "home automation not available"}
        try:
            fn = getattr(ctx.home_automation, "set_pin", None)
            if fn is None:
                return {"error": "no GPIO controller available"}
            fn(int(pin), bool(value))
            return {"pin": int(pin), "value": bool(value)}
        except Exception as e:
            return {"error": str(e)}

    # ---- Web search (DuckDuckGo Instant Answers, free & keyless) --------

    @tool(category="web", registry=reg)
    async def search_web(query: str) -> dict:
        """Look up a quick answer from DuckDuckGo's instant-answer API.

        query: what to look up
        """
        import aiohttp
        url = "https://api.duckduckgo.com/"
        params = {"q": query, "format": "json", "no_html": "1", "no_redirect": "1"}
        try:
            timeout = aiohttp.ClientTimeout(total=6)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params) as r:
                    data = await r.json(content_type=None)
        except Exception as e:
            return {"error": str(e)}
        answer = data.get("AbstractText") or data.get("Answer") or ""
        related = [t.get("Text") for t in data.get("RelatedTopics", []) if isinstance(t, dict) and t.get("Text")]
        return {"answer": answer, "related": related[:3], "source": data.get("AbstractURL", "")}

    return reg


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


# ---------------------------------------------------------------------------
# Provider-neutral tool-call loop
# ---------------------------------------------------------------------------


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ToolResult:
    id: str
    name: str
    ok: bool
    content: Any
    error: Optional[str] = None


async def run_tool_calls(calls: List[ToolCall], registry: Optional[ToolRegistry] = None) -> List[ToolResult]:
    """Execute a batch of tool calls concurrently."""
    reg = registry or _GLOBAL_REGISTRY
    async def _one(c: ToolCall) -> ToolResult:
        out = await reg.invoke(c.name, c.arguments)
        return ToolResult(
            id=c.id,
            name=c.name,
            ok=out["ok"],
            content=out.get("result"),
            error=out.get("error"),
        )
    return await asyncio.gather(*[_one(c) for c in calls])
