"""Tests for ai.plugins — drop-in plugin loader."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ai.plugins import PluginLoader
from ai.tools import ToolRegistry


def test_discover_returns_empty_when_dir_missing(tmp_path):
    loader = PluginLoader(plugins_dir=tmp_path / "nonexistent", registry=ToolRegistry())
    assert loader.discover() == []


def test_discover_skips_underscore_prefixed_files(tmp_path):
    (tmp_path / "good.py").write_text("pass\n")
    (tmp_path / "_private.py").write_text("pass\n")
    (tmp_path / "not_py.txt").write_text("nope")
    loader = PluginLoader(plugins_dir=tmp_path, registry=ToolRegistry())
    paths = loader.discover()
    assert len(paths) == 1
    assert paths[0].name == "good.py"


def test_load_all_registers_tools_from_plugin(tmp_path):
    reg = ToolRegistry()
    plugin = tmp_path / "greet_plugin.py"
    plugin.write_text(
        "from ai.tools import tool\n"
        "from tests.test_plugins import _REGISTRY_HOLDER\n"
        "@tool(registry=_REGISTRY_HOLDER['reg'])\n"
        "def greet(name: str) -> str:\n"
        "    '''Say hello to someone.\\n\\n    name: who to greet\\n    '''\n"
        "    return f'hello {name}'\n"
    )
    _REGISTRY_HOLDER["reg"] = reg
    loader = PluginLoader(plugins_dir=tmp_path, registry=reg)
    results = loader.load_all()
    assert len(results) == 1
    info = results[0]
    assert info.ok is True
    assert info.name == "greet_plugin"
    assert "greet" in reg.names()


def test_broken_plugin_does_not_stop_good_ones(tmp_path):
    reg = ToolRegistry()
    _REGISTRY_HOLDER["reg"] = reg
    (tmp_path / "broken.py").write_text("raise ImportError('oops')\n")
    (tmp_path / "good.py").write_text(
        "from ai.tools import tool\n"
        "from tests.test_plugins import _REGISTRY_HOLDER\n"
        "@tool(registry=_REGISTRY_HOLDER['reg'])\n"
        "def ok() -> str:\n"
        "    '''ok tool'''\n"
        "    return 'ok'\n"
    )
    loader = PluginLoader(plugins_dir=tmp_path, registry=reg)
    results = loader.load_all()
    by_name = {r.name: r for r in results}
    assert by_name["broken"].ok is False
    assert "oops" in (by_name["broken"].error or "")
    assert by_name["good"].ok is True
    assert "ok" in reg.names()


def test_load_all_on_empty_dir_returns_empty(tmp_path):
    loader = PluginLoader(plugins_dir=tmp_path, registry=ToolRegistry())
    assert loader.load_all() == []


# Shared holder so plugins written to tmp_path can reach the test registry.
_REGISTRY_HOLDER: dict = {}
