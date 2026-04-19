"""Tests for ai.vad — VoiceActivityDetector implementations."""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from ai.vad import RMSVad, VoiceActivityDetector, create_vad


def _silence(n_samples: int) -> bytes:
    return struct.pack(f"<{n_samples}h", *([0] * n_samples))


def _tone(n_samples: int, amplitude: int = 10000) -> bytes:
    # Alternating +amp / -amp = square wave ≈ high RMS.
    vals = [amplitude if i % 2 == 0 else -amplitude for i in range(n_samples)]
    return struct.pack(f"<{n_samples}h", *vals)


def test_rms_vad_silence_returns_false():
    v = RMSVad(threshold=500, onset_frames=1)
    assert v.is_speech(_silence(512), 16000) is False


def test_rms_vad_loud_frame_after_onset_triggers():
    v = RMSVad(threshold=500, onset_frames=3, release_frames=10)
    assert v.is_speech(_tone(512), 16000) is False
    assert v.is_speech(_tone(512), 16000) is False
    # Third loud frame flips to speech.
    assert v.is_speech(_tone(512), 16000) is True


def test_rms_vad_hysteresis_requires_release_frames_to_drop():
    v = RMSVad(threshold=500, onset_frames=1, release_frames=3)
    v.is_speech(_tone(512), 16000)  # in_speech = True
    # One silent frame alone shouldn't drop back to silence.
    v.is_speech(_silence(512), 16000)
    assert v._in_speech is True
    v.is_speech(_silence(512), 16000)
    v.is_speech(_silence(512), 16000)
    # After release_frames consecutive silent frames, drops.
    assert v.is_speech(_silence(512), 16000) is False


def test_reset_clears_streaks():
    v = RMSVad(threshold=500, onset_frames=1)
    v.is_speech(_tone(512), 16000)
    v.reset()
    assert v._in_speech is False
    # Won't immediately trigger again without another loud frame.
    assert v.is_speech(_silence(512), 16000) is False


def test_create_vad_prefers_rms_when_asked():
    vad = create_vad(prefer="rms")
    assert vad.name == "rms"
    assert isinstance(vad, VoiceActivityDetector)


def test_create_vad_auto_falls_back_to_rms_when_model_missing(tmp_path):
    missing = tmp_path / "does_not_exist.onnx"
    vad = create_vad(prefer="auto", model_path=missing)
    assert vad.name == "rms"


def test_create_vad_silero_raises_when_model_missing(tmp_path):
    missing = tmp_path / "does_not_exist.onnx"
    with pytest.raises(RuntimeError):
        create_vad(prefer="silero", model_path=missing)


def test_rms_vad_conforms_to_protocol():
    v = RMSVad()
    assert isinstance(v, VoiceActivityDetector)
    # Required method signatures exist.
    assert callable(v.is_speech)
    assert callable(v.reset)
