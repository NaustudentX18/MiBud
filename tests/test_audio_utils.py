"""
tests/test_audio_utils.py
Tests for audio utility functions — audioop replacement and VAD
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_rms_level_returns_int():
    """rms_level() must return an integer RMS value."""
    from utils.audio_utils import rms_level

    # 16-bit signed audio at 0 amplitude = RMS 0
    silent_audio = bytes(1024)  # all zeros
    rms = rms_level(silent_audio, width=2)
    assert isinstance(rms, int), f"Expected int, got {type(rms)}"
    assert rms == 0, f"Silent audio should have RMS 0, got {rms}"


def test_rms_level_detects_amplitude():
    """rms_level() must return higher value for louder audio."""
    from utils.audio_utils import rms_level
    import struct

    # Create audio with a sine wave at moderate amplitude
    # Max int16 = 32767
    samples = [int(16000 * ((i % 200) / 200 * 2 - 1)) for i in range(200)]
    audio = b"".join(struct.pack("<h", s) for s in samples)

    rms = rms_level(audio, width=2)
    assert rms > 0, f"Non-silent audio should have RMS > 0, got {rms}"
    assert rms < 20000, f"RMS seems too high: {rms}"


def test_rms_level_matches_audioop_behavior():
    """rms_level() should produce similar values to audioop.rms for same input."""
    import audioop
    from utils.audio_utils import rms_level

    import struct
    samples = [500, -500, 1000, -1000, 0, 0, 0] * 50
    audio = b"".join(struct.pack("<h", s) for s in samples)

    rms_struct = rms_level(audio, width=2)
    rms_audioop = audioop.rms(audio, 2)

    # Should match exactly
    assert rms_struct == rms_audioop, f"rms_struct={rms_struct} vs audioop={rms_audioop}"


def test_vad_detect_returns_bool():
    """VAD detect() must return a bool."""
    from ai.wakeword import VoiceActivityDetector
    import asyncio

    vad = VoiceActivityDetector(threshold=200)
    silent = bytes(1024)
    result = asyncio.get_event_loop().run_until_complete(vad.detect(silent))
    assert isinstance(result, bool), f"Expected bool, got {type(result)}"


def test_vad_threshold_settable():
    """VAD threshold must be settable."""
    from ai.wakeword import VoiceActivityDetector

    vad = VoiceActivityDetector(threshold=200)
    vad.set_threshold(300)
    assert vad.threshold == 300


def test_wakeword_stop_closes_audio_device(monkeypatch):
    """WakeWordDetector.stop() must close the PCM device."""
    from ai.wakeword import WakeWordDetector
    from core.config import Config

    close_called = []

    class MockPCM:
        def __init__(self):
            self.closed = False
        def read(self):
            return (0, b"\x00" * 1024)
        def close(self):
            close_called.append(True)
            self.closed = True

    import ai.wakeword
    mock_alsaaudio = type("alsaaudio", (), {
        "PCM": lambda *a, **kw: MockPCM(),
        "PCM_CAPTURE": 1,
        "PCM_NORMAL": 0,
        "PCM_FORMAT_S16_LE": 1,
    })
    monkeypatch.setattr(ai.wakeword, "_alsaaudio", mock_alsaaudio)

    config = Config()
    ww = WakeWordDetector(config)
    ww._enabled = True
    ww.is_initialized = True  # Skip async init; test doesn't use openWakeWord
    ww._detector = None  # Force VAD mode

    import asyncio

    async def test():
        await ww.start()
        await asyncio.sleep(0.05)
        await ww.stop()
        return len(close_called) > 0

    result = asyncio.get_event_loop().run_until_complete(test())
    assert result, "PCM.close() was not called during stop()"