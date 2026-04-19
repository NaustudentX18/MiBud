"""
Tests for the long-term memory + RAG store.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

numpy = pytest.importorskip("numpy")

from ai.memory import FactExtractor, HashingEmbedder, MemoryStore


def _make_store(tmp_path):
    return MemoryStore(path=tmp_path / "memory.db", embedder=HashingEmbedder(dim=128))


def test_embedding_is_normalised_and_deterministic():
    e = HashingEmbedder(dim=64)
    v1 = asyncio.run(e.embed("hello world"))
    v2 = asyncio.run(e.embed("hello world"))
    assert v1.shape == (64,)
    assert numpy.allclose(v1, v2)
    assert abs(float(numpy.linalg.norm(v1)) - 1.0) < 1e-5


def test_remember_and_recall(tmp_path):
    m = _make_store(tmp_path)
    asyncio.run(m.remember_fact("User's name is Alex.", category="profile"))
    asyncio.run(m.remember_fact("User loves espresso.", category="preference"))
    asyncio.run(m.remember_fact("User lives in Denver.", category="profile"))

    hits = asyncio.run(m.recall("what coffee does the user drink?", k=3))
    assert hits
    assert any("espresso" in h.fact for h in hits)

    # Category filter via list_facts.
    profile = m.list_facts(category="profile")
    assert {f.fact for f in profile} >= {"User's name is Alex.", "User lives in Denver."}


def test_dedup_on_repeat(tmp_path):
    m = _make_store(tmp_path)
    first = asyncio.run(m.remember_fact("User's name is Alex.", category="profile"))
    again = asyncio.run(m.remember_fact("User's name is Alex.", category="profile"))
    assert first == again
    assert m.stats()["facts"] == 1


def test_profile_roundtrip(tmp_path):
    m = _make_store(tmp_path)
    m.set_profile("name", "Alex")
    m.set_profile("timezone", "America/Denver")
    assert m.get_profile("name") == "Alex"
    assert m.all_profile() == {"name": "Alex", "timezone": "America/Denver"}


def test_session_summary_written(tmp_path):
    m = _make_store(tmp_path)
    m.add_turn("user", "My name is Alex.")
    m.add_turn("assistant", "Nice to meet you, Alex.")
    m.add_turn("user", "I live in Denver.")
    m.add_turn("assistant", "Got it.")
    summary = asyncio.run(m.end_session())
    assert summary
    sessions = m.list_recent_sessions(limit=5)
    assert len(sessions) == 1
    assert "Alex" in sessions[0]["summary"] or "Denver" in sessions[0]["summary"]


def test_context_block_aggregates_everything(tmp_path):
    m = _make_store(tmp_path)
    m.set_profile("name", "Alex")
    asyncio.run(m.remember_fact("User is allergic to peanuts.", category="profile"))
    block = asyncio.run(m.build_context_block("peanut butter sandwich", k=3))
    assert "User profile" in block
    assert "peanut" in block.lower()


def test_fact_extractor_catches_common_patterns(tmp_path):
    m = _make_store(tmp_path)
    fx = FactExtractor(m)
    asyncio.run(fx.extract("Hi, my name is Sam and I live in Portland."))
    asyncio.run(fx.extract("I love old synthesizers."))
    facts = {f.fact for f in m.list_facts()}
    assert any("Sam" in f for f in facts)
    assert any("Portland" in f for f in facts)
    assert any("synthesizers" in f for f in facts)
    # Structured profile slots should be populated.
    assert m.get_profile("name") == "Sam"
    assert m.get_profile("location").startswith("Portland")


def test_clear_all_wipes_everything(tmp_path):
    m = _make_store(tmp_path)
    asyncio.run(m.remember_fact("User likes mangoes.", category="preference"))
    m.set_profile("name", "Pat")
    m.add_turn("user", "hi")
    m.clear_all()
    s = m.stats()
    assert s["facts"] == 0
    assert s["profile_keys"] == 0
    assert s["conversations"] == 0
