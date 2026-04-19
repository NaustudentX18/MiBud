"""
Tests for the streaming sentence buffer + TTS pipeline.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ai.streaming import SentenceBuffer, stream_to_speech


def test_sentence_buffer_basic_split():
    buf = SentenceBuffer()
    buf.push("Hello there. ")
    ready = buf.ready()
    assert ready == ["Hello there."]
    assert buf.ready() == []
    buf.push("How are you? I'm fine.")
    ready = buf.ready()
    assert ready == ["How are you?", "I'm fine."]


def test_sentence_buffer_ignores_abbreviations():
    buf = SentenceBuffer()
    buf.push("Call Mr. Smith about the order.")
    # "Mr." alone shouldn't flush — needs the real sentence-ender.
    assert buf.ready() == ["Call Mr. Smith about the order."]


def test_sentence_buffer_flush_returns_tail():
    buf = SentenceBuffer()
    buf.push("no trailing punctuation")
    assert buf.ready() == []
    assert buf.flush() == "no trailing punctuation"


def test_sentence_buffer_token_dripfeed():
    buf = SentenceBuffer()
    out = []
    for ch in "Hi. How are you?":
        buf.push(ch)
        out.extend(buf.ready())
    out.extend([buf.flush()] if buf.flush() else [])
    assert out == ["Hi.", "How are you?"]


def test_stream_to_speech_order_and_stats():
    class FakeTTS:
        def __init__(self):
            self.said = []
        async def speak(self, text):
            self.said.append(text)

    async def run():
        tts = FakeTTS()

        async def token_iter():
            for chunk in ["Hello there. ", "How ", "are ", "you? ", "Goodbye."]:
                yield chunk

        text, stats = await stream_to_speech(token_iter(), tts)
        return tts.said, text, stats

    said, text, stats = asyncio.run(run())
    assert said == ["Hello there.", "How are you?", "Goodbye."]
    assert text == "Hello there. How are you? Goodbye."
    assert stats.total_sentences == 3
    assert stats.first_sentence_ms is not None


def test_stream_to_speech_swallows_tts_errors():
    class BrokenTTS:
        async def speak(self, text):
            raise RuntimeError("no speaker")

    async def run():
        async def iter_():
            yield "Hello. "
        text, stats = await stream_to_speech(iter_(), BrokenTTS())
        return text, stats

    text, stats = asyncio.run(run())
    # Error in TTS should not raise out to the caller.
    assert text == "Hello. "
    assert stats.total_sentences == 1
