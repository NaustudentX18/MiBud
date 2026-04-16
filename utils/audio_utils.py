"""
utils/audio_utils.py
Audio utility functions — replaces deprecated audioop module
"""
import struct


def rms_level(audio: bytes, width: int = 2) -> int:
    """Calculate RMS level of audio data (replaces audioop.rms).

    Args:
        audio: raw audio bytes (little-endian signed integers)
        width: bytes per sample (2 = 16-bit, 4 = 32-bit)

    Returns:
        RMS level as integer
    """
    if not audio or len(audio) < width:
        return 0

    fmt = "<h" if width == 2 else "<i"
    total = 0
    count = 0
    for i in range(0, len(audio) - (len(audio) % width), width):
        sample = struct.unpack_from(fmt, audio, i)[0]
        total += sample * sample
        count += 1

    if count == 0:
        return 0

    return int((total / count) ** 0.5)