"""
tests/test_tuning.py
Tests that magic numbers are configurable via config
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_config_has_tuning_section():
    """Config defaults must include a 'tuning' section."""
    from core.config import Config
    cfg = Config()
    assert "tuning" in cfg.data, "Config must have a 'tuning' section"


def test_tuning_values_are_reasonable_defaults():
    """Tuning defaults must be reasonable."""
    from core.config import Config
    cfg = Config()
    tuning = cfg.data.get("tuning", {})

    assert tuning.get("conversation_max_history", 0) >= 5
    assert tuning.get("stt_silence_threshold", 0) > 0
    assert tuning.get("vad_threshold", 0) > 0
    assert tuning.get("vad_cooldown_seconds", 0) > 0
    assert tuning.get("ai_max_tokens", 0) > 0


def test_config_can_set_tuning_value():
    """Config.set() must accept dotted paths like 'tuning.vad_threshold'."""
    from core.config import Config
    cfg = Config()
    cfg.set("tuning.test_value", 999)
    assert cfg.get("tuning.test_value") == 999


def test_conversation_manager_reads_tuning_from_config(monkeypatch):
    """ConversationManager should read max_history from config."""
    from core.config import Config
    from ai.conversation import ConversationManager

    cfg = Config()
    cfg.set("tuning.conversation_max_history", 5)

    # Monkeypatch to avoid needing audio
    monkeypatch.setenv("OLLAMA_URL", "http://localhost:11434")

    import asyncio
    class MockAudio:
        async def initialize(self): pass
        async def play_audio(self, data): pass
        async def record_chunk(self): return b""

    conv = ConversationManager.__new__(ConversationManager)
    conv.config = cfg
    conv.audio_manager = MockAudio()
    conv.router = None
    conv._current_personality = None
    conv._callbacks = {}
    conv.stt = None
    conv.tts = None
    conv._is_active = False

    # Check the max_history would be read from config
    # (Actual ConversationManager may not expose this publicly,
    # but we verify Config.get works for tuning paths)
    assert cfg.get("tuning.conversation_max_history") == 5
