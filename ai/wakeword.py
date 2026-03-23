"""
MiBud - Voice Activity Detection & Wake Word
openWakeWord integration for voice wake detection
"""

import asyncio
import logging
from typing import Callable, Optional, List
from pathlib import Path

log = logging.getLogger("MiBud")


class WakeWordDetector:
    """Wake word detection using openWakeWord"""
    
    def __init__(self, config):
        self.config = config
        self.is_initialized = False
        self.is_listening = False
        self._detector = None
        self._audio_task = None
        self._callback: Optional[Callable] = None
        self._enabled = config.get("wake_word.enabled", True)
        self._words = config.get("wake_word.words", ["hey mibud"])
        self._sensitivity = config.get("wake_word.sensitivity", 0.5)
        
    async def initialize(self):
        """Initialize wake word detector"""
        log.info("🎤 Initializing wake word detector...")
        
        if not self._enabled:
            log.info("🎤 Wake word disabled in config")
            self.is_initialized = True
            return
            
        try:
            # Try openWakeWord
            try:
                from openwakeword import WakeWordClassifier
                
                self._model_paths = []
                for word in self._words:
                    # Try to find or download model
                    model_path = self._get_model_path(word)
                    if model_path.exists():
                        self._model_paths.append(str(model_path))
                        
                if self._model_paths:
                    self._detector = WakeWordClassifier(
                        models=self._model_paths,
                        inference_framework="tflite"
                    )
                    log.info(f"🎤 Wake word detector ready with {len(self._model_paths)} models")
                else:
                    log.warning("🎤 No wake word models found")
                    
            except ImportError:
                log.warning("🎤 openWakeWord not available, using alternative method")
                await self._init_alternative()
                
        except Exception as e:
            log.warning(f"🎤 Wake word init warning: {e}")
            
        self.is_initialized = True
        
    async def _init_alternative(self):
        """Initialize alternative wake word detection"""
        # Could use pvporcupine or snowboy here
        log.info("🎤 Using threshold-based wake word detection")
        
    def _get_model_path(self, word: str) -> Path:
        """Get model path for word"""
        models_dir = Path(__file__).parent.parent.parent / "models" / "wakewords"
        models_dir.mkdir(parents=True, exist_ok=True)
        return models_dir / f"{word.replace(' ', '_')}.tflite"
        
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
        
        # Start audio capture task
        self._audio_task = asyncio.create_task(self._audio_loop())
        
    async def stop(self):
        """Stop listening for wake words"""
        self.is_listening = False
        
        if self._audio_task:
            self._audio_task.cancel()
            self._audio_task = None
            
        log.info("🎤 Wake word listening stopped")
        
    async def _audio_loop(self):
        """Audio capture loop for wake word detection"""
        try:
            import audioop
            import alsaaudio
            
            # Setup audio capture
            device = alsaaudio.PCM(
                alsaaudio.PCM_CAPTURE,
                alsaaudio.PCM_NORMAL,
                device=self.config.get("hardware.audio_input_device", "plughw:1,0")
            )
            device.setrate(16000)
            device.setchannels(1)
            device.setformat(alsaaudio.PCM_FORMAT_S16_LE)
            device.setperiodsize(1024)
            
            log.info("🎤 Audio loop started for wake word")
            
            while self.is_listening:
                try:
                    _, data = device.read()
                    if data:
                        # Check for wake word
                        if self._detector:
                            prediction = self._detector.predict(data)
                            # Check if any model triggered
                            for model_name, score in prediction.items():
                                if score > self._sensitivity:
                                    log.info(f"🎤 Wake word detected: {model_name} ({score:.2f})")
                                    if self._callback:
                                        await self._callback(model_name)
                                        
                except Exception as e:
                    log.debug(f"Wake word detection: {e}")
                    
                await asyncio.sleep(0.01)
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.warning(f"Audio loop error: {e}")
            
    async def add_custom_word(self, word: str, model_path: str = None):
        """Add custom wake word"""
        if word not in self._words:
            self._words.append(word)
            
        # Could trigger model download/training here
        log.info(f"🎤 Added custom wake word: {word}")
        
    def get_words(self) -> List[str]:
        """Get list of active wake words"""
        return self._words.copy()


class VoiceActivityDetector:
    """Voice activity detection for speech presence"""
    
    def __init__(self, threshold: float = 200):
        self.threshold = threshold
        self.is_speech = False
        
    async def detect(self, audio_data: bytes) -> bool:
        """Detect if speech is present in audio"""
        try:
            import audioop
            rms = audioop.rms(audio_data, 2)
            self.is_speech = rms > self.threshold
            return self.is_speech
        except:
            return False
            
    def set_threshold(self, threshold: float):
        """Set detection threshold"""
        self.threshold = threshold
