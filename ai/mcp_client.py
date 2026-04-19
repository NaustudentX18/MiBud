"""
ai/mcp_client.py — v3 Model Context Protocol client.

Spawns a local MCP server as a subprocess over stdio, speaks the minimal
subset of the protocol we need (``initialize``, ``tools/list``, ``tools/call``),
and proxies every discovered tool into MiBud's :class:`ToolRegistry` so the
LLM can invoke them like any built-in.

This is deliberately a minimal hand-rolled client rather than a dep on the
``mcp`` Python SDK — we need it to cold-start in <200 ms on a Pi Zero 2 W,
and the SDK's asyncio + websockets baggage is overkill for stdio.

Protocol reference: https://modelcontextprotocol.io/specification

What's supported:
  • stdio transport (single subprocess, JSON-RPC 2.0 framed by newline)
  • initialize / initialized handshake
  • tools/list → auto-register every returned tool
  • tools/call → bridged to MiBud ToolSpec.func

What's out of scope (for now):
  • Resources, prompts, sampling, websockets/SSE transport
  • Server-initiated requests
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ai.tools import ToolParam, ToolRegistry, ToolSpec, _annotation_to_json, get_registry

log = logging.getLogger("MiBud")

PROTOCOL_VERSION = "2024-11-05"


@dataclass
class MCPServerConfig:
    """Describes a single MCP server to spawn."""

    name: str
    command: str
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    timeout_s: float = 10.0

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MCPServerConfig":
        return cls(
            name=str(d["name"]),
            command=str(d["command"]),
            args=list(d.get("args") or []),
            env=dict(d.get("env") or {}),
            enabled=bool(d.get("enabled", True)),
            timeout_s=float(d.get("timeout_s", 10.0)),
        )


class MCPProtocolError(RuntimeError):
    """Raised when the remote server returns an error or the framing breaks."""


class MCPServer:
    """
    A single MCP stdio subprocess. Not re-entrant safe across instances of the
    same server — spawn once per config and reuse.
    """

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._pending: Dict[str, asyncio.Future] = {}
        self._tools: List[Dict[str, Any]] = []
        self._id_counter = 0
        self._write_lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    @property
    def tools(self) -> List[Dict[str, Any]]:
        return list(self._tools)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> List[ToolSpec]:
        """Spawn the server, perform the handshake, return proxied ToolSpecs."""
        if self.is_running:
            return []

        env = {**os.environ, **self.config.env}
        log.info(f"🔌 mcp: spawning '{self.config.name}' ({self.config.command})")
        self._proc = await asyncio.create_subprocess_exec(
            self.config.command,
            *self.config.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._reader_task = asyncio.create_task(self._read_loop())

        await self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mibud", "version": "3.0"},
            },
        )
        await self._notify("notifications/initialized", {})

        listed = await self._request("tools/list", {})
        self._tools = list(listed.get("tools") or [])
        log.info(f"🔌 mcp: '{self.config.name}' exposed {len(self._tools)} tool(s)")
        return self._make_specs()

    async def stop(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reader_task = None
        if self._proc is not None and self._proc.returncode is None:
            try:
                self._proc.terminate()
                try:
                    await asyncio.wait_for(self._proc.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    self._proc.kill()
                    await self._proc.wait()
            except ProcessLookupError:
                pass
        self._proc = None
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(MCPProtocolError("server stopped"))
        self._pending.clear()

    # ------------------------------------------------------------------
    # Tool proxying
    # ------------------------------------------------------------------

    def _make_specs(self) -> List[ToolSpec]:
        specs: List[ToolSpec] = []
        for t in self._tools:
            specs.append(self._spec_from_tool_decl(t))
        return specs

    def _spec_from_tool_decl(self, decl: Dict[str, Any]) -> ToolSpec:
        raw_name = str(decl.get("name") or "unnamed")
        # Namespace the tool to prevent collisions with built-ins.
        qualified = f"mcp_{self.config.name}_{raw_name}"
        description = str(decl.get("description") or raw_name)
        schema = decl.get("inputSchema") or {}
        props = schema.get("properties") or {}
        required = set(schema.get("required") or [])

        params: List[ToolParam] = []
        for pname, pdef in props.items():
            ptype = str(pdef.get("type") or "string")
            # Map JSON schema types to our internal type vocabulary. The
            # registry already accepts the JSON names verbatim, so this is
            # a pass-through with a fallback for unknowns.
            if ptype not in {"string", "integer", "number", "boolean", "array", "object"}:
                ptype = _annotation_to_json(ptype)
            params.append(
                ToolParam(
                    name=pname,
                    type=ptype,
                    description=str(pdef.get("description") or ""),
                    required=pname in required,
                    enum=pdef.get("enum"),
                )
            )

        async def _proxy(**kwargs: Any) -> Any:
            return await self.call_tool(raw_name, kwargs)

        return ToolSpec(
            name=qualified,
            description=description,
            params=params,
            func=_proxy,
            category=f"mcp:{self.config.name}",
            side_effects=True,  # MCP tools are untrusted; assume side effects.
        )

    async def call_tool(self, name: str, args: Dict[str, Any]) -> Any:
        """Invoke a tool on the remote server."""
        result = await self._request(
            "tools/call", {"name": name, "arguments": args or {}}
        )
        if isinstance(result, dict) and result.get("isError"):
            msg = _extract_text(result) or "tool error"
            raise MCPProtocolError(f"{name}: {msg}")
        return _extract_text(result) or result

    # ------------------------------------------------------------------
    # Framing / JSON-RPC
    # ------------------------------------------------------------------

    def _next_id(self) -> str:
        self._id_counter += 1
        return f"{self.config.name}-{self._id_counter}"

    async def _request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self.is_running:
            raise MCPProtocolError("server not running")
        msg_id = self._next_id()
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = fut
        payload = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
            "params": params,
        }
        await self._send(payload)
        try:
            return await asyncio.wait_for(fut, timeout=self.config.timeout_s)
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            raise MCPProtocolError(f"'{method}' timed out after {self.config.timeout_s}s")

    async def _notify(self, method: str, params: Dict[str, Any]) -> None:
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        await self._send(payload)

    async def _send(self, payload: Dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise MCPProtocolError("server stdin closed")
        line = (json.dumps(payload) + "\n").encode("utf-8")
        async with self._write_lock:
            self._proc.stdin.write(line)
            await self._proc.stdin.drain()

    async def _read_loop(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        stdout = self._proc.stdout
        while True:
            try:
                line = await stdout.readline()
            except Exception as e:
                log.debug(f"mcp '{self.config.name}' read error: {e}")
                break
            if not line:
                break
            try:
                msg = json.loads(line.decode("utf-8"))
            except json.JSONDecodeError:
                continue
            self._dispatch(msg)
        # Fail any outstanding waiters on EOF.
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(MCPProtocolError("server EOF"))
        self._pending.clear()

    def _dispatch(self, msg: Dict[str, Any]) -> None:
        msg_id = msg.get("id")
        if msg_id is None:
            return  # notification from the server; ignored
        fut = self._pending.pop(str(msg_id), None)
        if fut is None or fut.done():
            return
        if "error" in msg:
            err = msg["error"]
            fut.set_exception(
                MCPProtocolError(f"{err.get('code')}: {err.get('message')}")
            )
            return
        fut.set_result(msg.get("result") or {})


def _extract_text(result: Any) -> Optional[str]:
    """MCP tool results often wrap text in a ``content`` list. Flatten that."""
    if not isinstance(result, dict):
        return None
    content = result.get("content")
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
        if parts:
            return "\n".join(parts)
    return None


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class MCPManager:
    """Owns the fleet of MCP servers and their registered tools."""

    def __init__(self, registry: Optional[ToolRegistry] = None) -> None:
        self._registry = registry or get_registry()
        self._servers: Dict[str, MCPServer] = {}
        self._registered: Dict[str, List[str]] = {}

    @property
    def servers(self) -> Dict[str, MCPServer]:
        return dict(self._servers)

    async def start_server(self, config: MCPServerConfig) -> List[str]:
        """Spawn one server and register its tools. Returns the tool names."""
        if not config.enabled:
            return []
        if config.name in self._servers:
            log.debug(f"mcp server '{config.name}' already running")
            return list(self._registered.get(config.name) or [])
        server = MCPServer(config)
        specs = await server.start()
        self._servers[config.name] = server
        names: List[str] = []
        for spec in specs:
            self._registry.register(spec)
            names.append(spec.name)
        self._registered[config.name] = names
        return names

    async def start_all(self, configs: List[MCPServerConfig]) -> Dict[str, List[str]]:
        """Start every server, skipping failures (they're logged but non-fatal)."""
        out: Dict[str, List[str]] = {}
        for cfg in configs:
            try:
                out[cfg.name] = await self.start_server(cfg)
            except Exception as e:
                log.warning(f"🔌 mcp: '{cfg.name}' failed to start: {e}")
                out[cfg.name] = []
        return out

    async def stop_server(self, name: str) -> None:
        server = self._servers.pop(name, None)
        if server is not None:
            await server.stop()
        for tool_name in self._registered.pop(name, []):
            self._registry._tools.pop(tool_name, None)  # noqa: SLF001

    async def stop_all(self) -> None:
        for name in list(self._servers):
            await self.stop_server(name)

    def status(self) -> Dict[str, Any]:
        out = {}
        for name, srv in self._servers.items():
            out[name] = {
                "running": srv.is_running,
                "tools": list(self._registered.get(name) or []),
                "command": srv.config.command,
            }
        return out
