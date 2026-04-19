"""
ai/trace.py — v3 structured conversation trace.

Writes one JSONL line per turn to ``data/trace.log`` with timing, token counts,
tool calls, barge-in state, and truncated text. Rotates at a configurable size
with a single ``.1`` rollover so we never fill the Pi's SD card.

Consumed by ``/api/v3/trace``.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("MiBud")


class TraceLog:
    """Append-only JSONL trace with single-file rotation.

    Parameters
    ----------
    path :
        Destination file. Parent directory is created lazily.
    max_bytes :
        Soft cap. When the file exceeds this, it's renamed to ``<path>.1`` and
        a fresh log is opened. Default 1 MiB.
    keep_recent :
        How many most-recent entries ``recent()`` returns. Default 200.
    """

    def __init__(
        self,
        path: Path | str = "data/trace.log",
        *,
        max_bytes: int = 1 << 20,
        keep_recent: int = 200,
    ) -> None:
        self.path = Path(path)
        self.max_bytes = int(max_bytes)
        self.keep_recent = int(keep_recent)
        self._lock = threading.Lock()
        self._recent: List[Dict[str, Any]] = []
        self._dropped = 0

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def write(self, record: Dict[str, Any]) -> None:
        """Append a single record. Never raises."""
        entry = {"ts": time.time(), **record}
        with self._lock:
            self._recent.append(entry)
            if len(self._recent) > self.keep_recent:
                self._dropped += len(self._recent) - self.keep_recent
                self._recent = self._recent[-self.keep_recent :]
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._rotate_if_needed()
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            except OSError as e:
                log.warning(f"trace write failed: {e}")

    def write_turn(
        self,
        *,
        user_text: str,
        assistant_text: str,
        tool_calls: Optional[List[str]] = None,
        listen_ms: float = 0.0,
        think_ms: float = 0.0,
        speak_ms: float = 0.0,
        total_ms: float = 0.0,
        barged_in: bool = False,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Convenience wrapper for DialogSession turn records."""
        rec = {
            "type": "turn",
            "user": _truncate(user_text, 400),
            "assistant": _truncate(assistant_text, 600),
            "tool_calls": tool_calls or [],
            "listen_ms": round(listen_ms, 1),
            "think_ms": round(think_ms, 1),
            "speak_ms": round(speak_ms, 1),
            "total_ms": round(total_ms, 1),
            "barged_in": bool(barged_in),
        }
        if provider:
            rec["provider"] = provider
        if model:
            rec["model"] = model
        if extra:
            rec.update(extra)
        self.write(rec)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def recent(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        with self._lock:
            data = list(self._recent)
        if limit is None or limit >= len(data):
            return data
        return data[-limit:]

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            turns = [r for r in self._recent if r.get("type") == "turn"]
            barges = sum(1 for r in turns if r.get("barged_in"))
            avg_total = (
                sum(r.get("total_ms", 0.0) for r in turns) / len(turns)
                if turns
                else 0.0
            )
            return {
                "recent_turns": len(turns),
                "barge_ins": barges,
                "avg_total_ms": round(avg_total, 1),
                "dropped_from_ring": self._dropped,
                "path": str(self.path),
            }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _rotate_if_needed(self) -> None:
        try:
            if not self.path.exists():
                return
            if self.path.stat().st_size < self.max_bytes:
                return
        except OSError:
            return
        backup = self.path.with_suffix(self.path.suffix + ".1")
        try:
            if backup.exists():
                backup.unlink()
            os.replace(self.path, backup)
        except OSError as e:
            log.debug(f"trace rotate failed: {e}")


def _truncate(s: str, n: int) -> str:
    if s is None:
        return ""
    s = str(s)
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"
