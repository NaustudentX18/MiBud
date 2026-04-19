"""
MiBud AI - Streaming Pipeline

Streams LLM tokens straight into TTS, sentence by sentence, so the first
words come out of the speaker in under a second instead of waiting for the
full answer.

Pieces:
- `SentenceBuffer`: accumulates partial tokens and emits complete sentences
  on demand.
- `stream_to_speech(text_iter, tts)`: consumes an async iterator of token
  chunks, sends each completed sentence to TTS, keeps the text stream
  decoupled from the audio playback.
- `iter_lines(...)`: provider-agnostic helper for normalising streaming LLM
  responses into plain text chunks.

Works with the same TTSManager from ai/tts.py via its `speak()` method.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import AsyncIterator, Callable, List, Optional

log = logging.getLogger("MiBud")

# End-of-sentence detection. Avoids splitting on "e.g." or "Mr."
_ABBREV = {"mr", "mrs", "ms", "dr", "e.g", "i.e", "etc", "jr", "sr", "st", "vs", "no", "fig"}
_SENT_END = re.compile(r"([\.!\?][\)\]\"'`”’]*)(\s+|$)")


class SentenceBuffer:
    """Accumulate tokens and hand back complete sentences.

    Usage:
        buf = SentenceBuffer()
        buf.push("Hello there. How")
        buf.ready() -> ["Hello there."]
        buf.push(" are you?")
        buf.ready() -> ["How are you?"]
        buf.flush() -> any remaining tail text
    """

    def __init__(self, min_chars: int = 8) -> None:
        self._buf = ""
        self._min_chars = min_chars

    def push(self, chunk: str) -> None:
        if chunk:
            self._buf += chunk

    def ready(self) -> List[str]:
        """Return and remove any complete sentences."""
        out: List[str] = []
        while True:
            s = self._extract_one()
            if s is None:
                break
            out.append(s)
        return out

    def _extract_one(self) -> Optional[str]:
        text = self._buf
        for m in _SENT_END.finditer(text):
            end = m.end(1)
            candidate = text[:end].strip()
            if not candidate:
                continue
            # Avoid breaking on known abbreviations ("e.g.").
            tail = candidate.split()[-1].rstrip(".,!?").lower() if candidate.split() else ""
            if tail in _ABBREV and end < len(text):
                continue
            if len(candidate) < self._min_chars and end < len(text):
                continue
            self._buf = text[m.end():]
            return candidate
        return None

    def flush(self) -> Optional[str]:
        tail = self._buf.strip()
        self._buf = ""
        return tail or None


# ---------------------------------------------------------------------------
# Streaming helpers
# ---------------------------------------------------------------------------


@dataclass
class StreamStats:
    first_sentence_ms: Optional[int] = None
    total_sentences: int = 0
    total_chars: int = 0


async def stream_to_speech(
    token_iter: AsyncIterator[str],
    tts,
    on_sentence: Optional[Callable[[str], None]] = None,
    collect: bool = True,
    start_time: Optional[float] = None,
) -> tuple[str, StreamStats]:
    """Consume an async token stream, speak sentences as they're ready.

    Parameters
    ----------
    token_iter : async iterator yielding str chunks (can be partial words).
    tts : object with ``async speak(text)``; TTSManager satisfies this.
    on_sentence : optional callback invoked for each complete sentence *before*
        speech starts (useful for the display / logs).
    collect : if True, returns the full concatenated text.
    start_time : ``time.monotonic()`` reference for first-sentence latency.

    Returns (full_text, stats).
    """

    import time
    t0 = start_time if start_time is not None else time.monotonic()
    buf = SentenceBuffer()
    full: list[str] = []
    stats = StreamStats()
    speak_queue: asyncio.Queue[Optional[str]] = asyncio.Queue(maxsize=4)

    async def _speaker():
        while True:
            item = await speak_queue.get()
            if item is None:
                return
            try:
                await tts.speak(item)
            except Exception as e:
                log.error(f"🔊 stream tts error: {e}")

    speaker_task = asyncio.create_task(_speaker())

    try:
        async for chunk in token_iter:
            if not chunk:
                continue
            buf.push(chunk)
            if collect:
                full.append(chunk)
            stats.total_chars += len(chunk)
            for sentence in buf.ready():
                if stats.first_sentence_ms is None:
                    stats.first_sentence_ms = int((time.monotonic() - t0) * 1000)
                if on_sentence is not None:
                    try:
                        on_sentence(sentence)
                    except Exception:
                        pass
                stats.total_sentences += 1
                await speak_queue.put(sentence)
        tail = buf.flush()
        if tail:
            if stats.first_sentence_ms is None:
                stats.first_sentence_ms = int((time.monotonic() - t0) * 1000)
            if on_sentence is not None:
                try:
                    on_sentence(tail)
                except Exception:
                    pass
            stats.total_sentences += 1
            await speak_queue.put(tail)
    finally:
        await speak_queue.put(None)
        await speaker_task

    return ("".join(full) if collect else "", stats)


# ---------------------------------------------------------------------------
# Provider adapters
# ---------------------------------------------------------------------------


async def openai_stream(client, model: str, messages: list, **kwargs) -> AsyncIterator[str]:
    """Wrap an OpenAI (or OpenAI-compatible) streaming completion into plain chunks."""
    def _sync_stream():
        return client.chat.completions.create(
            model=model, messages=messages, stream=True, **kwargs
        )
    stream = await asyncio.to_thread(_sync_stream)
    for event in stream:
        try:
            delta = event.choices[0].delta
            part = getattr(delta, "content", None) or ""
        except Exception:
            part = ""
        if part:
            yield part
        await asyncio.sleep(0)


async def anthropic_stream(client, model: str, messages: list, max_tokens: int = 500, system: str = "", **kwargs) -> AsyncIterator[str]:
    """Stream text deltas from the Anthropic Messages API."""

    def _sync_stream():
        return client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            **kwargs,
        )

    # Anthropic's stream() returns a context manager; we can't hold it across
    # awaits cleanly, so we drain into a queue on a worker thread.
    q: asyncio.Queue = asyncio.Queue(maxsize=64)
    loop = asyncio.get_running_loop()
    SENTINEL = object()

    def _worker():
        try:
            with _sync_stream() as s:
                for text in s.text_stream:
                    if text:
                        loop.call_soon_threadsafe(q.put_nowait, text)
        except Exception as e:  # pragma: no cover — runtime path
            loop.call_soon_threadsafe(q.put_nowait, ("__err__", str(e)))
        finally:
            loop.call_soon_threadsafe(q.put_nowait, SENTINEL)

    task = asyncio.create_task(asyncio.to_thread(_worker))
    try:
        while True:
            item = await q.get()
            if item is SENTINEL:
                return
            if isinstance(item, tuple) and item and item[0] == "__err__":
                log.error(f"anthropic stream error: {item[1]}")
                return
            yield item  # type: ignore[misc]
    finally:
        await task


async def ollama_stream(url: str, model: str, prompt: str, timeout: float = 60.0) -> AsyncIterator[str]:
    """Stream tokens from an Ollama /api/generate endpoint."""
    import aiohttp
    import json as _json
    payload = {"model": model, "prompt": prompt, "stream": True}
    cli_timeout = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(timeout=cli_timeout) as session:
        async with session.post(f"{url}/api/generate", json=payload) as r:
            async for line in r.content:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = _json.loads(line)
                except Exception:
                    continue
                part = data.get("response", "")
                if part:
                    yield part
                if data.get("done"):
                    return
