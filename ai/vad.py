"""
ai/vad.py — v3 Voice Activity Detection abstraction.

Offers a pluggable interface with two implementations:

* :class:`RMSVad` — zero-dep energy-threshold detector with a small state
  machine for debouncing. Matches v2's behaviour and always ships.
* :class:`SileroVAD` — onnxruntime-backed Silero VAD (~2 MB model) with far
  higher precision. Loaded lazily and only if the model + runtime are both
  available on the device. Falls back to RMSVad otherwise.

The interface is deliberately narrow:

    is_speech(pcm_frame: bytes, sample_rate: int) -> bool
    reset()

Callers feed 20–30 ms frames of 16-bit signed-PCM and get a boolean back.
Everything else (ring buffers, max-silence cutoff, barge-in signalling) lives
in the dialog layer.
"""
from __future__ import annotations

import logging
import os
import struct
from pathlib import Path
from typing import Protocol, runtime_checkable

import warnings

try:  # Python 3.13 removed audioop from the stdlib.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        import audioop as _audioop  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised only on 3.13+
    _audioop = None

log = logging.getLogger("MiBud")


# Silero expects exactly these frame sizes for the respective rates.
_SILERO_FRAME_SAMPLES = {8000: 256, 16000: 512}


@runtime_checkable
class VoiceActivityDetector(Protocol):
    """Structural interface for VAD backends."""

    name: str

    def is_speech(self, pcm_frame: bytes, sample_rate: int) -> bool: ...

    def reset(self) -> None: ...


# ---------------------------------------------------------------------------
# Baseline: RMS + hysteresis
# ---------------------------------------------------------------------------


class RMSVad:
    """
    Energy-threshold VAD with per-frame RMS and a two-state hysteresis.

    Parameters
    ----------
    threshold :
        RMS above which a frame is considered loud. Tune per mic / gain.
    onset_frames :
        Number of consecutive loud frames required to flip to "speech".
        Higher = fewer false positives, slower onset detection.
    release_frames :
        Consecutive quiet frames required to flip back to "silence".
    """

    name = "rms"

    def __init__(
        self,
        threshold: int = 500,
        onset_frames: int = 3,
        release_frames: int = 10,
    ) -> None:
        self.threshold = int(threshold)
        self.onset_frames = int(onset_frames)
        self.release_frames = int(release_frames)
        self._loud_streak = 0
        self._quiet_streak = 0
        self._in_speech = False

    def reset(self) -> None:
        self._loud_streak = 0
        self._quiet_streak = 0
        self._in_speech = False

    def is_speech(self, pcm_frame: bytes, sample_rate: int) -> bool:
        # audioop.rms expects a width (bytes per sample). Assume 16-bit.
        if _audioop is not None:
            try:
                rms = _audioop.rms(pcm_frame, 2)
            except Exception:
                rms = _pure_rms_s16(pcm_frame)
        else:
            rms = _pure_rms_s16(pcm_frame)
        if rms >= self.threshold:
            self._loud_streak += 1
            self._quiet_streak = 0
        else:
            self._quiet_streak += 1
            self._loud_streak = 0
        if not self._in_speech and self._loud_streak >= self.onset_frames:
            self._in_speech = True
        elif self._in_speech and self._quiet_streak >= self.release_frames:
            self._in_speech = False
        return self._in_speech


def _pure_rms_s16(pcm: bytes) -> float:
    """Fallback RMS for when audioop is unavailable (Python 3.13+)."""
    n = len(pcm) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack(f"<{n}h", pcm[: n * 2])
    return (sum(s * s for s in samples) / n) ** 0.5


# ---------------------------------------------------------------------------
# Silero (optional, ONNX)
# ---------------------------------------------------------------------------


class SileroVAD:
    """
    ONNX-runtime wrapper for the Silero VAD v5 single-file model.

    The model file is not shipped in-repo (licensing + size). On first load
    we look for it at::

        data/silero_vad.onnx

    If it's absent or onnxruntime isn't installed, :func:`create` returns an
    :class:`RMSVad` instead.
    """

    name = "silero"

    # Minimum probability to treat a frame as speech. 0.5 is the Silero default.
    DEFAULT_THRESHOLD = 0.5

    def __init__(
        self,
        session,  # onnxruntime.InferenceSession
        threshold: float = DEFAULT_THRESHOLD,
    ) -> None:
        import numpy as np  # local import to keep top-level cheap

        self._np = np
        self._session = session
        self.threshold = float(threshold)
        self._h = np.zeros((2, 1, 64), dtype=np.float32)
        self._c = np.zeros((2, 1, 64), dtype=np.float32)

    def reset(self) -> None:
        np = self._np
        self._h = np.zeros((2, 1, 64), dtype=np.float32)
        self._c = np.zeros((2, 1, 64), dtype=np.float32)

    def is_speech(self, pcm_frame: bytes, sample_rate: int) -> bool:
        np = self._np
        expected = _SILERO_FRAME_SAMPLES.get(sample_rate)
        if expected is None:
            return False
        if len(pcm_frame) != expected * 2:
            return False
        # 16-bit PCM -> float32 in [-1, 1]
        audio = np.frombuffer(pcm_frame, dtype=np.int16).astype(np.float32) / 32768.0
        audio = audio.reshape(1, -1)
        try:
            outputs = self._session.run(
                None,
                {
                    "input": audio,
                    "h": self._h,
                    "c": self._c,
                    "sr": np.array(sample_rate, dtype=np.int64),
                },
            )
        except Exception as e:
            log.debug(f"silero inference failed, returning silence: {e}")
            return False
        prob, self._h, self._c = outputs[0], outputs[1], outputs[2]
        return float(prob.item()) >= self.threshold


def create_vad(
    *,
    prefer: str = "auto",
    model_path: Path | str = "data/silero_vad.onnx",
    rms_threshold: int = 500,
) -> VoiceActivityDetector:
    """
    Build the best VAD available on this device.

    ``prefer``:
      * ``"auto"`` — try silero, fall back to RMS (default)
      * ``"rms"``  — always use RMS
      * ``"silero"`` — try silero, raise if unavailable

    Always returns *something* in auto mode so the caller never has to worry
    about VAD being missing.
    """
    if prefer == "rms":
        return RMSVad(threshold=rms_threshold)

    mp = Path(model_path)
    if not mp.exists() or not mp.is_file():
        if prefer == "silero":
            raise RuntimeError(f"silero model not found at {mp}")
        return RMSVad(threshold=rms_threshold)

    try:
        import onnxruntime as ort  # type: ignore
    except ImportError:
        if prefer == "silero":
            raise RuntimeError("onnxruntime not installed; cannot load silero VAD")
        return RMSVad(threshold=rms_threshold)

    try:
        sess_opts = ort.SessionOptions()
        # Pi Zero 2 W has 4 cores; cap inter/intra to 1 so VAD never starves
        # the rest of the pipeline.
        sess_opts.intra_op_num_threads = 1
        sess_opts.inter_op_num_threads = 1
        session = ort.InferenceSession(str(mp), sess_options=sess_opts)
    except Exception as e:
        if prefer == "silero":
            raise
        log.warning(f"silero load failed ({e}); using RMS VAD")
        return RMSVad(threshold=rms_threshold)
    log.info(f"🎙️  VAD: silero loaded ({os.path.getsize(mp)} bytes)")
    return SileroVAD(session)


__all__ = ["VoiceActivityDetector", "RMSVad", "SileroVAD", "create_vad"]
