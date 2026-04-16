"""
MiBud Hardware - Audio Manager
WM8960 Audio Codec + ALSA Audio Handling
"""

import os
import sys
import logging
import platform
import asyncio
from typing import Optional, Callable
from dataclasses import dataclass

log = logging.getLogger("MiBud")

# WhisPlay driver path
_WHISPLAY_DRIVER = "/home/pi/Whisplay/Driver"

@dataclass
class AudioConfig:
    """Audio configuration"""
    input_device: str = "plughw:1,0"
    output_device: str = "default"
    sample_rate: int = 16000
    channels: int = 1
    chunk_size: int = 1024


class AudioManager:
    """Manages audio input/output for WhisPlay HAT"""
    
    def __init__(self, config: AudioConfig = None):
        self.config = config or AudioConfig()
        self.is_initialized = False
        self.is_rpi = platform.machine().startswith(('arm', 'aarch'))
        self._board = None
        self._recorder = None
        self._player = None
        self._volume = 70
        self._is_muted = False
        self._level_callback: Optional[Callable] = None
        
    async def initialize(self):
        """Initialize audio system"""
        log.info("🔊 Initializing audio...")
        
        if not self.is_rpi:
            log.info("🔊 Non-RPi platform - simulation mode")
            self.is_initialized = True
            return
            
        try:
            # Try WhisPlay driver
            if os.path.exists(_WHISPLAY_DRIVER):
                sys.path.append(_WHISPLAY_DRIVER)
                from WhisPlay import WhisPlayBoard
                self._board = WhisPlayBoard()
                log.info("🔊 WhisPlay audio initialized")
            else:
                log.warning("🔊 WhisPlay driver not found")
                
            # Try ALSA
            try:
                import alsaaudio
                self._alsamixer = alsaaudio.Mixer()
                self._alsamixer.setvolume(self._volume)
                log.info("🔊 ALSA mixer initialized")
            except Exception as e:
                log.warning(f"🔊 ALSA not available: {e}")
                
        except Exception as e:
            log.warning(f"🔊 Audio init warning: {e}")
            
        self.is_initialized = True
        log.info("✅ Audio initialized")
        
    def set_volume(self, level: int):
        """Set volume (0-100)"""
        self._volume = max(0, min(100, level))
        if not self._is_muted and hasattr(self, '_alsamixer'):
            self._alsamixer.setvolume(self._volume)
            
    def get_volume(self) -> int:
        """Get current volume"""
        return self._volume
        
    def mute(self):
        """Mute audio"""
        self._is_muted = True
        if hasattr(self, '_alsamixer'):
            self._alsamixer.setvolume(0)
            
    def unmute(self):
        """Unmute audio"""
        self._is_muted = False
        if hasattr(self, '_alsamixer'):
            self._alsamixer.setvolume(self._volume)
            
    async def record_chunk(self, timeout: float = 5.0) -> bytes:
        """Record audio chunk"""
        if not self.is_initialized:
            return b''
            
        try:
            import alsaaudio
            device = alsaaudio.PCM(alsaaudio.PCM_CAPTURE, 
                                   alsaaudio.PCM_NORMAL,
                                   device=self.config.input_device)
            device.setrate(self.config.sample_rate)
            device.setchannels(self.config.channels)
            device.setformat(alsaaudio.PCM_FORMAT_S16_LE)
            device.setperiodsize(self.config.chunk_size)
            
            # Read audio data
            data = device.read()
            if data:
                return data[1]
        except Exception as e:
            log.debug(f"Record chunk: {e}")
            
        return b''
        
    async def play_audio(self, audio_data: bytes):
        """Play audio data"""
        if not self.is_initialized or self._is_muted:
            return
            
        try:
            import alsaaudio
            device = alsaaudio.PCM(alsaaudio.PCM_PLAYBACK,
                                   alsaaudio.PCM_NORMAL,
                                   device=self.config.output_device)
            device.setrate(self.config.sample_rate)
            device.setchannels(2)
            device.setformat(alsaaudio.PCM_FORMAT_S16_LE)
            device.write(audio_data)
        except Exception as e:
            log.debug(f"Play audio: {e}")
            
    async def check_audio_level(self) -> float:
        """Check current audio input level (RMS)"""
        try:
            import alsaaudio
            device = alsaaudio.PCM(alsaaudio.PCM_CAPTURE,
                                   alsaaudio.PCM_NORMAL,
                                   device=self.config.input_device)
            device.setrate(self.config.sample_rate)
            device.setchannels(self.config.channels)
            device.setformat(alsaaudio.PCM_FORMAT_S16_LE)
            
            data = device.read()
            if data and data[1]:
                from utils.audio_utils import rms_level
                rms = rms_level(data[1], 2)
                return rms
        except Exception:
            pass
        return 0.0
        
    def set_level_callback(self, callback: Callable[[float], None]):
        """Set callback for audio level updates"""
        self._level_callback = callback
        
    def _get_recorder_device(self):
        """Get ALSA recorder device for conversation manager"""
        try:
            import alsaaudio
            device = alsaaudio.PCM(
                alsaaudio.PCM_CAPTURE,
                alsaaudio.PCM_NORMAL,
                device=self.config.input_device
            )
            device.setrate(self.config.sample_rate)
            device.setchannels(self.config.channels)
            device.setformat(alsaaudio.PCM_FORMAT_S16_LE)
            device.setperiodsize(self.config.chunk_size)
            return device
        except Exception as e:
            log.warning(f"Failed to get recorder device: {e}")
            return None
            
    async def cleanup(self):
        """Cleanup audio resources"""
        log.info("🔊 Audio cleanup")
        if hasattr(self, '_alsamixer'):
            self._alsamixer = None
