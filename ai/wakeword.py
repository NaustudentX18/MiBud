"""
MiBud - Voice Activity Detection & Wake Word
openWakeWord integration for voice wake detection
"""

try:
    import alsaaudio as _alsaaudio
except ImportError:
    _alsaaudio = None
import asyncio
import logging
from typing import Callable, Optional, List
from pathlib import Path
import numpy as np

log = logging.getLogger("MiBud")


class WakeWordDetector:
    """Wake word detection using openWakeWord"""
    
    def __init__(self, config, audio_manager=None):
        self.config = config
        self.audio_manager = audio_manager
        self.is_initialized = False
        self.is_listening = False
        self._detector = None
        self._audio_device = None
        self._vad_detector = None
        self._audio_task = None
        self._callback: Optional[Callable] = None
        self._enabled = config.get("wake_word.enabled", True)
        self._words = config.get("wake_word.words", ["hey mibud", "ok google"])
        self._sensitivity = config.get("wake_word.sensitivity", 0.5)
        self._vad_threshold = 200
        self._frame_count = 0
        self._consecutive_frames = 0
        self._min_trigger_frames = 3
        self._last_trigger_time = 0
        self._cooldown_seconds = 2.0
        
    async def initialize(self):
        """Initialize wake word detector"""
        log.info("🎤 Initializing wake word detector...")
        
        if not self._enabled:
            log.info("🎤 Wake word disabled in config")
            self.is_initialized = True
            return
            
        try:
            try:
                from openwakeword import WakeWordClassifier
                log.info("🎤 Loading openWakeWord models...")
                
                model_path = self._get_model_path("hey_mibud")
                if model_path.exists():
                    self._detector = WakeWordClassifier(
                        models=[str(model_path)],
                        inference_framework="tflite"
                    )
                    log.info(f"🎤 Wake word detector loaded with model: {model_path.name}")
                else:
                    log.warning("🎤 No wake word model found - using VAD mode")
                    
            except ImportError:
                log.warning("🎤 openWakeWord not available - using VAD mode")
            except Exception as e:
                log.warning(f"🎤 Model loading failed: {e} - using VAD mode")
                
        except Exception as e:
            log.warning(f"🎤 Wake word init warning: {e}")
            
        self.is_initialized = True
        log.info("✅ Wake word detector ready")
        
    def _get_model_path(self, word: str) -> Path:
        """Get model path for word"""
        models_dir = Path(__file__).parent.parent / "models" / "wakewords"
        models_dir.mkdir(parents=True, exist_ok=True)
        return models_dir / f"{word}.tflite"
        
    def set_callback(self, callback: Callable):
        """Set callback for wake word detection"""
        self._callback = callback
        
    async def start(self):
        """Start listening for wake words"""
        if not self._enabled or not self.is_initialized:
            return
            
        if self.is_listening:
            return
            
        self.is_listening = True
        log.info("🎤 Wake word listening started")
        
        self._audio_task = asyncio.create_task(self._audio_loop())
        
    async def stop(self):
        """Stop listening for wake words"""
        self.is_listening = False
        
        if self._audio_task:
            self._audio_task.cancel()
            try:
                await self._audio_task
            except asyncio.CancelledError:
                pass
            self._audio_task = None

        # Close PCM device to release audio hardware
        if self._audio_device is not None:
            try:
                self._audio_device.close()
            except Exception:
                pass
            self._audio_device = None

        log.info("🎤 Wake word listening stopped")
        
    async def _audio_loop(self):
        """Audio capture loop for wake word detection"""
        
        try:
            self._audio_device = _alsaaudio.PCM(
                _alsaaudio.PCM_CAPTURE,
                _alsaaudio.PCM_NORMAL,
                device=self.config.get("hardware.audio_input_device", "plughw:1,0")
            )
            self._audio_device.setrate(16000)
            self._audio_device.setchannels(1)
            self._audio_device.setformat(_alsaaudio.PCM_FORMAT_S16_LE)
            self._audio_device.setperiodsize(1024)
            device = self._audio_device

        except Exception as e:
            log.error(f"🎤 Failed to open audio device: {e}")
            return

        log.info("🎤 Audio loop started for wake word detection")

        # Calibrate VAD with first ~1 second of ambient audio
        try:
            from utils.audio_utils import rms_level
            calibration_chunks = []
            import time
            start = time.time()
            while time.time() - start < 1.0 and self.is_listening:
                _, cal_data = device.read()
                if cal_data:
                    calibration_chunks.append(cal_data)
                await asyncio.sleep(0.01)

            if calibration_chunks and hasattr(self, '_vad_detector') and self._vad_detector:
                await self._vad_detector.calibrate(calibration_chunks)
            elif calibration_chunks:
                # Inline calibration for VAD threshold
                levels = [rms_level(d, 2) for d in calibration_chunks if d]
                if levels:
                    import statistics
                    mean = statistics.mean(levels)
                    stdev = statistics.stdev(levels) if len(levels) > 1 else 0
                    self._vad_threshold = int(mean + 2 * stdev + 10)
                    log.info(f"🎤 VAD calibrated: threshold={self._vad_threshold}")
        except Exception as e:
            log.debug(f"VAD calibration skipped: {e}")
        
        while self.is_listening:
            try:
                _, data = device.read()
                if not data:
                    await asyncio.sleep(0.01)
                    continue
                    
                if self._detector:
                    prediction = self._detector.predict(data)
                    for model_name, score in prediction.items():
                        if score > self._sensitivity:
                            await self._handle_wake_word(model_name, score)
                else:
                    from utils.audio_utils import rms_level
                    rms = rms_level(data, 2)
                    await self._vad_check_by_rms(rms)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.debug(f"Wake word detection: {e}")
                await asyncio.sleep(0.01)
                
    async def _vad_check_by_rms(self, rms: int):
        """VAD check using RMS level (uses struct, not audioop)."""
        import time

        try:
            current_time = time.time()

            if rms > self._vad_threshold:
                self._consecutive_frames += 1
                self._frame_count += 1

                if (self._consecutive_frames >= self._min_trigger_frames and
                    current_time - self._last_trigger_time > self._cooldown_seconds):
                    self._last_trigger_time = current_time
                    await self._handle_wake_word("voice_activity", rms / 1000.0)
            else:
                self._consecutive_frames = 0

        except Exception as e:
            log.debug(f"VAD check: {e}")
            
    async def _handle_wake_word(self, model_name: str, score: float):
        """Handle detected wake word"""
        log.info(f"🎤 Wake word detected: {model_name} ({score:.2f})")
        
        if self._callback:
            try:
                await self._callback(model_name)
            except Exception as e:
                log.error(f"🎤 Callback error: {e}")
                
    async def add_custom_word(self, word: str, model_path: str = None):
        """Add custom wake word"""
        if word not in self._words:
            self._words.append(word)
        log.info(f"🎤 Added custom wake word: {word}")
        
    def get_words(self) -> List[str]:
        """Get list of active wake words"""
        return self._words.copy()
    
    def set_sensitivity(self, sensitivity: float):
        """Set detection sensitivity (0.0-1.0)"""
        self._sensitivity = max(0.1, min(1.0, sensitivity))
        
    def set_vad_threshold(self, threshold: int):
        """Set VAD threshold"""
        self._vad_threshold = max(50, min(1000, threshold))


class VoiceActivityDetector:
    """Voice activity detection for speech presence"""

    def __init__(self, threshold: float = 200):
        self.threshold = threshold
        self.is_speech = False

    async def detect(self, audio_data: bytes) -> bool:
        """Detect if speech is present in audio"""
        try:
            from utils.audio_utils import rms_level
            rms = rms_level(audio_data, 2)
            self.is_speech = rms > self.threshold
            return self.is_speech
        except Exception:
            return False

    def set_threshold(self, threshold: float):
        """Set detection threshold"""
        self.threshold = threshold

    async def calibrate(self, audio_chunks: List[bytes], samples: int = 10):
        """Calibrate VAD threshold to ambient noise level.

        Call this during startup with ~1 second of ambient audio.
        Sets threshold to mean RMS + 2 standard deviations.
        """
        from utils.audio_utils import rms_level
        levels = []

        for chunk in audio_chunks[:samples]:
            level = rms_level(chunk, width=2)
            levels.append(level)

        if levels:
            import statistics
            mean = statistics.mean(levels)
            stdev = statistics.stdev(levels) if len(levels) > 1 else 0
            self.threshold = int(mean + 2 * stdev + 10)
            log.info(f"🎤 VAD calibrated: threshold={self.threshold}")
