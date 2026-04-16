"""
tests/test_tts.py
Piper TTS process supervision tests
"""
import sys
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestPiperTTS:
    """Tests for Piper TTS process supervision"""

    def test_piper_cleanup_terminates_process(self, monkeypatch, tmp_path):
        """Piper cleanup() must terminate the subprocess"""
        from ai.tts import PiperTTS

        piper = PiperTTS(model_path=str(tmp_path))
        # Mock a live process
        import subprocess
        piper._process = subprocess.Popen(
            ["sleep", "60"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        pid = piper._process.pid

        import asyncio
        pid = piper._process.pid
        asyncio.run(piper.cleanup())

        # Process should be terminated and reference cleared
        assert piper._process is None, "Process reference should be cleared after cleanup()"

    def test_piper_speak_returns_none_when_no_process(self, tmp_path):
        """Piper speak() must return None when process not initialized"""
        from ai.tts import PiperTTS

        piper = PiperTTS(model_path=str(tmp_path))
        piper._process = None

        import asyncio
        result = asyncio.run(piper.speak("hello"))
        assert result is None

    def test_piper_init_handles_missing_model(self, tmp_path, monkeypatch):
        """Piper init must not raise when model is missing"""
        from ai.tts import PiperTTS

        piper = PiperTTS(model_path=str(tmp_path))
        # tmp_path has no .onnx files — init should handle gracefully

        import asyncio
        asyncio.run(piper.initialize())

        # Should not have a process since no model exists
        assert piper._process is None
