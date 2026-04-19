"""
ai/plugins.py — v3 drop-in Python plugin loader.

Scans ``plugins/`` (relative to repo root) for ``.py`` files, imports each one,
and lets their ``@tool`` decorators self-register into the global
:class:`ToolRegistry`. No subclassing, no manifest, no config — if a function
carries an ``@tool`` decorator the router will see it after ``load_all()``.

Isolation:
  • Each plugin is imported in its own module namespace so name collisions
    between plugins can't clobber each other.
  • Import errors in a single plugin are caught and logged; they never take
    down the whole boot.

Security:
  • Plugins execute arbitrary Python. This module is intentionally only
    activated when ``features.enable_plugins`` is true in config.json and
    plugins live under a directory that the device owner controls.
"""
from __future__ import annotations

import importlib.util
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from ai.tools import ToolRegistry, get_registry

log = logging.getLogger("MiBud")


@dataclass
class PluginInfo:
    name: str
    path: str
    ok: bool
    tools: List[str]
    error: Optional[str] = None


class PluginLoader:
    """Discovers and imports plugin .py files. Safe to call repeatedly."""

    def __init__(
        self,
        plugins_dir: Path | str = "plugins",
        registry: Optional[ToolRegistry] = None,
    ) -> None:
        self.plugins_dir = Path(plugins_dir)
        self._registry = registry or get_registry()
        self._loaded: Dict[str, PluginInfo] = {}

    @property
    def loaded(self) -> Dict[str, PluginInfo]:
        return dict(self._loaded)

    def discover(self) -> List[Path]:
        """Return every candidate .py file under ``plugins_dir`` (non-recursive)."""
        if not self.plugins_dir.exists() or not self.plugins_dir.is_dir():
            return []
        return sorted(
            p for p in self.plugins_dir.glob("*.py") if not p.name.startswith("_")
        )

    def load_all(self) -> List[PluginInfo]:
        """Import each plugin in isolation and return per-plugin results."""
        results: List[PluginInfo] = []
        for path in self.discover():
            info = self._load_one(path)
            self._loaded[info.name] = info
            results.append(info)
        ok = sum(1 for r in results if r.ok)
        if results:
            log.info(f"🔌 plugins: loaded {ok}/{len(results)} from {self.plugins_dir}")
        return results

    def _load_one(self, path: Path) -> PluginInfo:
        name = path.stem
        module_name = f"mibud_plugin_{name}"
        before = set(self._registry.names())
        try:
            spec = importlib.util.spec_from_file_location(module_name, path)
            if spec is None or spec.loader is None:
                return PluginInfo(
                    name=name,
                    path=str(path),
                    ok=False,
                    tools=[],
                    error="could not build module spec",
                )
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)  # type: ignore[union-attr]
        except Exception as e:  # pragma: no cover - surfaced via error field
            log.warning(f"🔌 plugins: '{name}' failed to load: {e}")
            sys.modules.pop(module_name, None)
            return PluginInfo(
                name=name,
                path=str(path),
                ok=False,
                tools=[],
                error=str(e),
            )
        added = sorted(set(self._registry.names()) - before)
        return PluginInfo(name=name, path=str(path), ok=True, tools=added)
