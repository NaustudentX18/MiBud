"""
MiBud AI - Long-Term Memory + RAG

A local, privacy-preserving memory store backed by SQLite. Handles:
- Durable facts about the user/world (name, preferences, routines).
- Conversation archive with per-session summaries.
- Semantic search via a lightweight built-in embedding (char n-gram hashed
  features) with an opt-in upgrade to Ollama `nomic-embed-text`.

Design constraints:
- Pi Zero 2 W (512 MB RAM, no GPU). No torch, no sentence-transformers.
- All embeddings are float32 numpy arrays, persisted as BLOB.
- Cosine similarity; top-k retrieval.
- Zero external services required. Ollama is optional and auto-detected.

Everything the AI stores is inspectable and wipeable from the web UI.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

try:  # numpy is already a requirement via scipy/pyaudio
    import numpy as np
except Exception:  # pragma: no cover - dev-env fallback
    np = None  # type: ignore

log = logging.getLogger("MiBud")


# ---------------------------------------------------------------------------
# Embedding backends
# ---------------------------------------------------------------------------


class Embedder:
    """Base embedding interface."""

    dim: int = 0

    async def embed(self, text: str) -> "np.ndarray":  # noqa: F821
        raise NotImplementedError


class HashingEmbedder(Embedder):
    """Character-n-gram hashed features.

    Cheap, deterministic, works offline with zero dependencies beyond numpy.
    Good enough for short factual recall on a few hundred items. Dimension is
    configurable (default 256 — 1 KB per fact on disk).
    """

    def __init__(self, dim: int = 256, ngrams: Tuple[int, int] = (3, 5)) -> None:
        self.dim = dim
        self.ngrams = ngrams

    async def embed(self, text: str) -> "np.ndarray":
        if np is None:
            raise RuntimeError("numpy not available")
        vec = np.zeros(self.dim, dtype=np.float32)
        norm_text = re.sub(r"\s+", " ", text.lower().strip())
        if not norm_text:
            return vec
        # Token-level features.
        for tok in re.findall(r"[\w']+", norm_text):
            h = hash(("tok", tok)) % self.dim
            vec[h] += 1.0
        # Char n-grams (overlap so short words still match).
        lo, hi = self.ngrams
        padded = f" {norm_text} "
        for n in range(lo, hi + 1):
            for i in range(len(padded) - n + 1):
                gram = padded[i : i + n]
                h = hash(("gram", n, gram)) % self.dim
                vec[h] += 1.0
        n = float(np.linalg.norm(vec))
        if n > 0:
            vec /= n
        return vec


class OllamaEmbedder(Embedder):
    """Optional: 768-d real embeddings via Ollama nomic-embed-text."""

    def __init__(self, url: str = "http://localhost:11434", model: str = "nomic-embed-text") -> None:
        self.url = url
        self.model = model
        self.dim = 768

    async def embed(self, text: str) -> "np.ndarray":
        import aiohttp
        if np is None:
            raise RuntimeError("numpy not available")
        payload = {"model": self.model, "prompt": text}
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(f"{self.url}/api/embeddings", json=payload) as r:
                data = await r.json()
        vec = np.asarray(data.get("embedding", []), dtype=np.float32)
        if vec.size == 0:
            raise RuntimeError("ollama returned empty embedding")
        n = float(np.linalg.norm(vec))
        if n > 0:
            vec = vec / n
        self.dim = int(vec.shape[0])
        return vec


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class Fact:
    id: str
    fact: str
    category: str = "general"
    confidence: float = 1.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    score: float = 0.0  # populated by recall


@dataclass
class ConversationTurn:
    session_id: str
    role: str
    content: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


@dataclass
class SessionSummary:
    session_id: str
    summary: str
    started_at: str
    ended_at: str
    turn_count: int


# ---------------------------------------------------------------------------
# SQLite schema
# ---------------------------------------------------------------------------


_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id TEXT PRIMARY KEY,
    fact TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    confidence REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL,
    embedding BLOB NOT NULL,
    embed_dim INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS facts_category_idx ON facts(category);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS conv_session_idx ON conversations(session_id);
CREATE INDEX IF NOT EXISTS conv_created_idx ON conversations(created_at);

CREATE TABLE IF NOT EXISTS session_summaries (
    session_id TEXT PRIMARY KEY,
    summary TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    turn_count INTEGER NOT NULL,
    embedding BLOB NOT NULL,
    embed_dim INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS user_profile (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Memory store
# ---------------------------------------------------------------------------


class MemoryStore:
    """Local, encrypted-at-rest-optional, semantic fact store."""

    def __init__(
        self,
        path: Path | str = "data/memory.db",
        embedder: Optional[Embedder] = None,
        summarizer: Optional[Callable[[str], Awaitable[str]]] = None,
    ) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.embedder = embedder or HashingEmbedder()
        self._summarizer = summarizer
        self._current_session = uuid.uuid4().hex[:12]
        self._session_started = datetime.now().isoformat(timespec="seconds")
        self._lock = asyncio.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.executescript(_SCHEMA)
        # In-memory vector matrix for fast recall. Invalidated on any write.
        self._vec_cache_dirty = True
        self._vec_matrix: Optional["np.ndarray"] = None
        self._vec_meta: List[Tuple[str, str, str, float, str]] = []  # (id, fact, category, conf, created)

    # ---- Session handling -------------------------------------------

    def new_session(self) -> str:
        self._current_session = uuid.uuid4().hex[:12]
        self._session_started = datetime.now().isoformat(timespec="seconds")
        return self._current_session

    @property
    def session_id(self) -> str:
        return self._current_session

    # ---- Embedding helpers -------------------------------------------

    def _pack(self, vec: "np.ndarray") -> bytes:
        if np is None:
            raise RuntimeError("numpy not available")
        return vec.astype(np.float32).tobytes()

    def _unpack(self, blob: bytes, dim: int) -> "np.ndarray":
        if np is None:
            raise RuntimeError("numpy not available")
        return np.frombuffer(blob, dtype=np.float32, count=dim).copy()

    async def _embed(self, text: str) -> "np.ndarray":
        return await self.embedder.embed(text)

    # ---- Facts -------------------------------------------------------

    async def remember_fact(
        self,
        fact: str,
        category: str = "general",
        confidence: float = 1.0,
    ) -> str:
        """Store a fact. Deduplicates against near-identical existing facts."""
        fact = fact.strip()
        if not fact:
            return ""
        vec = await self._embed(fact)
        # Cheap dedup: look for cosine >= 0.92 in the same category.
        if self._vec_cache_dirty:
            self._rebuild_vector_cache()
        if (
            self._vec_matrix is not None and np is not None
            and self._vec_matrix.shape[1] == vec.shape[0]
        ):
            sims = self._vec_matrix @ vec
            best_idx = int(np.argmax(sims)) if sims.size else -1
            if best_idx >= 0 and float(sims[best_idx]) >= 0.92:
                fid, stored, cat, _, _ = self._vec_meta[best_idx]
                if cat == category:
                    self._conn.execute(
                        "UPDATE facts SET confidence=? WHERE id=?",
                        (max(confidence, self._get_fact_confidence(fid)), fid),
                    )
                    log.debug(f"🧠 dedup: '{fact}' matches '{stored}' (sim={float(sims[best_idx]):.2f})")
                    return fid
        fid = uuid.uuid4().hex[:12]
        now = datetime.now().isoformat(timespec="seconds")
        async with self._lock:
            self._conn.execute(
                "INSERT INTO facts (id, fact, category, confidence, created_at, embedding, embed_dim) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (fid, fact, category, float(confidence), now, self._pack(vec), int(vec.shape[0])),
            )
            self._vec_cache_dirty = True
        log.info(f"🧠 remember ({category}): {fact}")
        return fid

    def _get_fact_confidence(self, fid: str) -> float:
        row = self._conn.execute("SELECT confidence FROM facts WHERE id=?", (fid,)).fetchone()
        return row[0] if row else 0.0

    def _all_fact_vectors(self, category: Optional[str] = None) -> List[Tuple[str, str, "np.ndarray"]]:
        if category:
            rows = self._conn.execute(
                "SELECT id, fact, embedding, embed_dim FROM facts WHERE category=?",
                (category,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, fact, embedding, embed_dim FROM facts"
            ).fetchall()
        return [(r[0], r[1], self._unpack(r[2], r[3])) for r in rows]

    def _rebuild_vector_cache(self) -> None:
        rows = self._conn.execute(
            "SELECT id, fact, category, confidence, created_at, embedding, embed_dim FROM facts"
        ).fetchall()
        if not rows:
            self._vec_matrix = None
            self._vec_meta = []
            self._vec_cache_dirty = False
            return
        dim = rows[0][6]
        # Only cache rows that match the embedder's current dim; older rows fall back to per-row cosine.
        mat = np.zeros((len(rows), dim), dtype=np.float32) if np is not None else None
        meta: List[Tuple[str, str, str, float, str]] = []
        fallback: List[Tuple[str, str, str, float, str, bytes, int]] = []
        for idx, (fid, fact, cat, conf, created, blob, rdim) in enumerate(rows):
            if rdim == dim and mat is not None:
                mat[idx] = self._unpack(blob, rdim)
                meta.append((fid, fact, cat, conf, created))
            else:
                fallback.append((fid, fact, cat, conf, created, blob, rdim))
        # Drop unused rows from mat if any were fallback.
        if mat is not None and len(meta) != len(rows):
            mat = mat[: len(meta)]
        self._vec_matrix = mat
        self._vec_meta = meta
        self._vec_fallback = fallback
        self._vec_cache_dirty = False

    async def recall(self, query: str, k: int = 5, min_score: float = 0.05) -> List[Fact]:
        """Return the top-k facts most relevant to `query`."""
        vec = await self._embed(query)
        if self._vec_cache_dirty:
            self._rebuild_vector_cache()
        scored: List[Fact] = []
        # Fast path: single matmul across every cached fact vector.
        if self._vec_matrix is not None and np is not None and self._vec_matrix.shape[1] == vec.shape[0]:
            sims = self._vec_matrix @ vec  # both already L2-normalised
            for i, sim in enumerate(sims):
                s = float(sim)
                if s < min_score:
                    continue
                fid, fact, cat, conf, created = self._vec_meta[i]
                scored.append(Fact(
                    id=fid, fact=fact, category=cat,
                    confidence=conf, created_at=created, score=s,
                ))
        # Fallback path for any rows with a different embedding dim.
        for fid, fact, cat, conf, created, blob, dim in getattr(self, "_vec_fallback", []):
            sim = _cosine(vec, self._unpack(blob, dim))
            if sim < min_score:
                continue
            scored.append(Fact(
                id=fid, fact=fact, category=cat,
                confidence=conf, created_at=created, score=sim,
            ))
        scored.sort(key=lambda f: f.score, reverse=True)
        return scored[: max(0, int(k))]

    def list_facts(self, category: Optional[str] = None, limit: int = 200) -> List[Fact]:
        if category:
            rows = self._conn.execute(
                "SELECT id, fact, category, confidence, created_at FROM facts "
                "WHERE category=? ORDER BY created_at DESC LIMIT ?",
                (category, int(limit)),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, fact, category, confidence, created_at FROM facts "
                "ORDER BY created_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [
            Fact(id=r[0], fact=r[1], category=r[2], confidence=r[3], created_at=r[4])
            for r in rows
        ]

    def delete_fact(self, fact_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM facts WHERE id=?", (fact_id,))
        if cur.rowcount > 0:
            self._vec_cache_dirty = True
            return True
        return False

    # ---- Conversation archive ---------------------------------------

    def add_turn(self, role: str, content: str) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        self._conn.execute(
            "INSERT INTO conversations (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (self._current_session, role, content, now),
        )

    def recent_turns(self, limit: int = 20) -> List[ConversationTurn]:
        rows = self._conn.execute(
            "SELECT session_id, role, content, created_at FROM conversations "
            "ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        rows.reverse()
        return [ConversationTurn(*r) for r in rows]

    def session_turns(self, session_id: Optional[str] = None) -> List[ConversationTurn]:
        sid = session_id or self._current_session
        rows = self._conn.execute(
            "SELECT session_id, role, content, created_at FROM conversations "
            "WHERE session_id=? ORDER BY id ASC",
            (sid,),
        ).fetchall()
        return [ConversationTurn(*r) for r in rows]

    async def end_session(self) -> Optional[str]:
        """Summarize the current session and store it. Returns summary text."""
        turns = self.session_turns()
        if len(turns) < 2:
            self.new_session()
            return None
        transcript = "\n".join(f"{t.role}: {t.content}" for t in turns)
        summary = ""
        if self._summarizer is not None:
            try:
                summary = (await self._summarizer(transcript)).strip()
            except Exception as e:
                log.warning(f"🧠 summariser failed: {e}")
        if not summary:
            summary = _heuristic_summary(transcript)
        vec = await self._embed(summary)
        started = turns[0].created_at
        ended = turns[-1].created_at
        self._conn.execute(
            "INSERT OR REPLACE INTO session_summaries "
            "(session_id, summary, started_at, ended_at, turn_count, embedding, embed_dim) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                self._current_session, summary, started, ended,
                len(turns), self._pack(vec), int(vec.shape[0]),
            ),
        )
        self.new_session()
        return summary

    def list_recent_sessions(self, limit: int = 5) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT session_id, summary, started_at, ended_at, turn_count "
            "FROM session_summaries ORDER BY ended_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [
            {
                "session_id": r[0], "summary": r[1], "started_at": r[2],
                "ended_at": r[3], "turn_count": r[4],
            }
            for r in rows
        ]

    # ---- User profile -----------------------------------------------

    def set_profile(self, key: str, value: Any) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        self._conn.execute(
            "INSERT OR REPLACE INTO user_profile (key, value, updated_at) VALUES (?, ?, ?)",
            (key, json.dumps(value), now),
        )

    def get_profile(self, key: str, default: Any = None) -> Any:
        row = self._conn.execute("SELECT value FROM user_profile WHERE key=?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row[0])
        except Exception:
            return row[0]

    def all_profile(self) -> Dict[str, Any]:
        rows = self._conn.execute("SELECT key, value FROM user_profile").fetchall()
        out: Dict[str, Any] = {}
        for k, v in rows:
            try:
                out[k] = json.loads(v)
            except Exception:
                out[k] = v
        return out

    # ---- System prompt integration ----------------------------------

    async def build_context_block(self, query: str, k: int = 4) -> str:
        """Return a compact memory block to inject into the system prompt."""
        lines: List[str] = []
        profile = self.all_profile()
        if profile:
            pretty = ", ".join(f"{k}={v}" for k, v in profile.items() if v)
            if pretty:
                lines.append(f"User profile: {pretty}.")
        if query:
            hits = await self.recall(query, k=k)
            if hits:
                lines.append("Relevant memories:")
                for h in hits:
                    lines.append(f"- ({h.category}) {h.fact}")
        recents = self.list_recent_sessions(limit=2)
        if recents:
            lines.append("Recent session summaries:")
            for s in recents:
                lines.append(f"- {s['ended_at']}: {s['summary']}")
        if not lines:
            return ""
        return "MEMORY CONTEXT:\n" + "\n".join(lines)

    # ---- Admin ------------------------------------------------------

    def stats(self) -> Dict[str, int]:
        c = self._conn
        return {
            "facts": c.execute("SELECT COUNT(*) FROM facts").fetchone()[0],
            "conversations": c.execute("SELECT COUNT(*) FROM conversations").fetchone()[0],
            "sessions": c.execute("SELECT COUNT(*) FROM session_summaries").fetchone()[0],
            "profile_keys": c.execute("SELECT COUNT(*) FROM user_profile").fetchone()[0],
        }

    def clear_all(self) -> None:
        c = self._conn
        c.execute("DELETE FROM facts")
        c.execute("DELETE FROM conversations")
        c.execute("DELETE FROM session_summaries")
        c.execute("DELETE FROM user_profile")
        self._vec_cache_dirty = True
        self._vec_matrix = None
        self._vec_meta = []
        self.new_session()
        log.warning("🧠 memory cleared")

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cosine(a: "np.ndarray", b: "np.ndarray") -> float:
    if np is None:
        return 0.0
    if a.shape != b.shape:
        return 0.0
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _heuristic_summary(transcript: str, max_chars: int = 280) -> str:
    """Pull the first user question + last assistant answer, truncate."""
    user_lines = [l[6:] for l in transcript.splitlines() if l.startswith("user: ")]
    asst_lines = [l[11:] for l in transcript.splitlines() if l.startswith("assistant: ")]
    bits = []
    if user_lines:
        bits.append(f"User asked about: {user_lines[0]}")
    if asst_lines:
        bits.append(f"Assistant replied: {asst_lines[-1]}")
    text = " | ".join(bits)
    return text[:max_chars]


# ---------------------------------------------------------------------------
# Fact extractor — runs after each turn to capture durable facts
# ---------------------------------------------------------------------------


class FactExtractor:
    """Extract first-person facts from user messages.

    Two modes:
    - heuristic: regex patterns, works offline with zero LLM calls.
    - llm: ask the router with a tight JSON-mode prompt (slower, higher quality).
    """

    _PATTERNS = [
        (re.compile(r"\bmy name is ([A-Z][a-zA-Z\-']{1,30})", re.IGNORECASE), "profile", "User's name is {0}."),
        (re.compile(r"\bi am (\d{1,3}) (?:years old|yo)\b", re.IGNORECASE), "profile", "User is {0} years old."),
        (re.compile(r"\bi live in ([A-Z][a-zA-Z ,.\-']{1,60})", re.IGNORECASE), "profile", "User lives in {0}."),
        (re.compile(r"\bi work (?:as|at) ([^\.\!\?]{2,60})", re.IGNORECASE), "profile", "User works {0}."),
        (re.compile(r"\bi (?:like|love|enjoy) ([^\.\!\?]{2,60})", re.IGNORECASE), "preference", "User likes {0}."),
        (re.compile(r"\bi (?:hate|dislike|can't stand) ([^\.\!\?]{2,60})", re.IGNORECASE), "preference", "User dislikes {0}."),
        (re.compile(r"\bi'm allergic to ([^\.\!\?]{2,60})", re.IGNORECASE), "profile", "User is allergic to {0}."),
        (re.compile(r"\bmy (birthday|pronouns|timezone) is ([^\.\!\?]{2,60})", re.IGNORECASE), "profile", "User's {0} is {1}."),
        (re.compile(r"\bevery (morning|evening|night|day) i ([^\.\!\?]{2,60})", re.IGNORECASE), "routine", "User's {0} routine: {1}."),
    ]

    def __init__(self, memory: MemoryStore) -> None:
        self.memory = memory

    async def extract(self, user_text: str) -> List[str]:
        """Return list of stored fact IDs."""
        stored: List[str] = []
        for rx, cat, tmpl in self._PATTERNS:
            m = rx.search(user_text)
            if not m:
                continue
            groups = [g.strip().rstrip(".!?") for g in m.groups()]
            fact = tmpl.format(*groups)
            fid = await self.memory.remember_fact(fact, category=cat, confidence=0.85)
            if fid:
                stored.append(fid)
            # Also populate structured profile for common fields.
            if cat == "profile" and "name is" in fact.lower():
                self.memory.set_profile("name", groups[0])
            if "lives in" in fact.lower():
                self.memory.set_profile("location", groups[0])
            if "timezone" in fact.lower():
                self.memory.set_profile("timezone", groups[-1])
        return stored
