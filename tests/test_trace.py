"""Tests for ai.trace — TraceLog JSONL writer."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ai.trace import TraceLog


def test_write_turn_persists_to_jsonl(tmp_path):
    tl = TraceLog(path=tmp_path / "trace.log")
    tl.write_turn(
        user_text="hi",
        assistant_text="hello there",
        listen_ms=100.0,
        think_ms=200.0,
        speak_ms=300.0,
        total_ms=600.0,
        provider="openrouter",
        model="gemini",
    )
    lines = (tmp_path / "trace.log").read_text().strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["type"] == "turn"
    assert rec["user"] == "hi"
    assert rec["assistant"] == "hello there"
    assert rec["provider"] == "openrouter"
    assert rec["model"] == "gemini"
    assert rec["listen_ms"] == 100.0


def test_recent_returns_most_recent_entries(tmp_path):
    tl = TraceLog(path=tmp_path / "trace.log", keep_recent=3)
    for i in range(5):
        tl.write({"type": "turn", "i": i})
    recent = tl.recent()
    assert [r["i"] for r in recent] == [2, 3, 4]
    assert tl.stats()["dropped_from_ring"] == 2


def test_long_text_is_truncated(tmp_path):
    tl = TraceLog(path=tmp_path / "trace.log")
    tl.write_turn(user_text="x" * 1000, assistant_text="y" * 2000)
    rec = tl.recent()[-1]
    assert len(rec["user"]) <= 400
    assert len(rec["assistant"]) <= 600
    assert rec["user"].endswith("…")


def test_rotation_moves_oldest_to_dot1(tmp_path):
    path = tmp_path / "trace.log"
    tl = TraceLog(path=path, max_bytes=256)
    for i in range(30):
        tl.write({"type": "turn", "user": "x" * 50, "i": i})
    assert path.exists()
    backup = path.with_suffix(".log.1")
    assert backup.exists()
    # Backup is the old content, current file is the recent content.
    assert backup.read_text() != ""
    assert path.read_text() != ""


def test_stats_reports_barge_ins_and_avg(tmp_path):
    tl = TraceLog(path=tmp_path / "trace.log")
    tl.write_turn(user_text="a", assistant_text="b", total_ms=100.0)
    tl.write_turn(user_text="c", assistant_text="d", total_ms=300.0, barged_in=True)
    s = tl.stats()
    assert s["recent_turns"] == 2
    assert s["barge_ins"] == 1
    assert s["avg_total_ms"] == 200.0


def test_write_survives_non_serialisable_extras(tmp_path):
    tl = TraceLog(path=tmp_path / "trace.log")

    class Weird:
        def __repr__(self):
            return "<Weird>"

    tl.write_turn(user_text="hi", assistant_text="hi", extra={"obj": Weird()})
    lines = (tmp_path / "trace.log").read_text().strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["obj"] == "<Weird>"
