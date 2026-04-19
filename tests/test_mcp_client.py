"""Tests for ai.mcp_client — stdio MCP server integration."""
from __future__ import annotations

import asyncio
import json
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from ai.mcp_client import MCPManager, MCPProtocolError, MCPServer, MCPServerConfig
from ai.tools import ToolRegistry


# A tiny line-delimited JSON-RPC MCP server implemented in Python.
# It supports initialize / tools/list / tools/call and nothing else.
MOCK_SERVER_SOURCE = textwrap.dedent("""
    import json, sys

    TOOLS = [
        {
            "name": "echo",
            "description": "Echo the input text back.",
            "inputSchema": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "text"}},
                "required": ["text"],
            },
        },
        {
            "name": "fail",
            "description": "Always returns an error result.",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
    ]

    def send(obj):
        sys.stdout.write(json.dumps(obj) + "\\n")
        sys.stdout.flush()

    for line in sys.stdin:
        msg = json.loads(line)
        mid = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or {}
        if method == "initialize":
            send({"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05"}})
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            if name == "echo":
                send({
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {"content": [{"type": "text", "text": args.get("text", "")}]},
                })
            elif name == "fail":
                send({
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {"isError": True, "content": [{"type": "text", "text": "boom"}]},
                })
            else:
                send({
                    "jsonrpc": "2.0",
                    "id": mid,
                    "error": {"code": -32601, "message": f"unknown tool {name}"},
                })
        elif mid is not None:
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "?"}})
""").strip()


@pytest.fixture
def mock_server_path(tmp_path: Path) -> Path:
    p = tmp_path / "mock_server.py"
    p.write_text(MOCK_SERVER_SOURCE)
    return p


def _cfg(path: Path, name: str = "mock") -> MCPServerConfig:
    return MCPServerConfig(
        name=name,
        command=sys.executable,
        args=["-u", str(path)],
        timeout_s=5.0,
    )


def test_server_config_from_dict_parses_all_fields():
    cfg = MCPServerConfig.from_dict({
        "name": "x",
        "command": "cmd",
        "args": ["a", "b"],
        "env": {"K": "V"},
        "enabled": False,
        "timeout_s": 2.5,
    })
    assert cfg.name == "x"
    assert cfg.args == ["a", "b"]
    assert cfg.env == {"K": "V"}
    assert cfg.enabled is False
    assert cfg.timeout_s == 2.5


def test_server_start_handshake_and_tool_list(mock_server_path):
    async def run():
        server = MCPServer(_cfg(mock_server_path))
        specs = await server.start()
        try:
            assert server.is_running
            names = [s.name for s in specs]
            assert "mcp_mock_echo" in names
            assert "mcp_mock_fail" in names
            echo_spec = next(s for s in specs if s.name == "mcp_mock_echo")
            # Param extracted from inputSchema.
            assert any(p.name == "text" and p.required for p in echo_spec.params)
        finally:
            await server.stop()
        assert not server.is_running

    asyncio.run(run())


def test_server_call_tool_returns_text(mock_server_path):
    async def run():
        server = MCPServer(_cfg(mock_server_path))
        specs = await server.start()
        try:
            echo = next(s for s in specs if s.name == "mcp_mock_echo")
            # Invoke through the proxy function the spec carries.
            reg = ToolRegistry()
            reg.register(echo)
            result = await reg.invoke("mcp_mock_echo", {"text": "hi there"})
            assert result["ok"] is True
            assert result["result"] == "hi there"
        finally:
            await server.stop()

    asyncio.run(run())


def test_server_call_tool_propagates_error(mock_server_path):
    async def run():
        server = MCPServer(_cfg(mock_server_path))
        specs = await server.start()
        try:
            reg = ToolRegistry()
            for s in specs:
                reg.register(s)
            result = await reg.invoke("mcp_mock_fail", {})
            assert result["ok"] is False
            assert "boom" in result["error"]
        finally:
            await server.stop()

    asyncio.run(run())


def test_manager_starts_registers_and_stops(mock_server_path):
    async def run():
        reg = ToolRegistry()
        mgr = MCPManager(registry=reg)
        names = await mgr.start_server(_cfg(mock_server_path))
        assert len(names) == 2
        assert set(names) <= set(reg.names())
        status = mgr.status()
        assert "mock" in status
        assert status["mock"]["running"] is True
        await mgr.stop_all()
        # Tools should be unregistered after stop.
        assert "mcp_mock_echo" not in reg.names()

    asyncio.run(run())


def test_manager_disabled_server_is_skipped(mock_server_path):
    async def run():
        cfg = _cfg(mock_server_path)
        cfg.enabled = False
        mgr = MCPManager(registry=ToolRegistry())
        names = await mgr.start_server(cfg)
        assert names == []

    asyncio.run(run())


def test_manager_start_all_tolerates_failures(mock_server_path):
    async def run():
        bad = MCPServerConfig(
            name="bad", command="/no/such/binary/please", timeout_s=2.0
        )
        good = _cfg(mock_server_path, name="good")
        reg = ToolRegistry()
        mgr = MCPManager(registry=reg)
        out = await mgr.start_all([bad, good])
        assert out["bad"] == []
        assert len(out["good"]) == 2
        await mgr.stop_all()

    asyncio.run(run())


def test_request_timeout_raises(mock_server_path, tmp_path):
    # A server that just echoes handshake then stalls forever.
    stall = tmp_path / "stall.py"
    stall.write_text(textwrap.dedent("""
        import json, sys, time
        for line in sys.stdin:
            msg = json.loads(line)
            if msg.get("method") == "initialize":
                sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {}}) + "\\n")
                sys.stdout.flush()
            elif msg.get("method") == "notifications/initialized":
                pass
            else:
                time.sleep(30)
    """))

    async def run():
        cfg = MCPServerConfig(
            name="stall", command=sys.executable, args=["-u", str(stall)], timeout_s=0.5
        )
        server = MCPServer(cfg)
        try:
            await server.start()
        except MCPProtocolError as e:
            assert "timed out" in str(e)
        finally:
            await server.stop()

    asyncio.run(run())
