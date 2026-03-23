"""
MiBud - Speech-to-Text (STT)
Handles voice transcription with multiple provider options
"""

import asyncio
import logging
import io
from typing import Optional, Callable
from pathlib import Path

log = logging.getLogger("MiBud")


class STTProvider:
    """Base STT provider"""
    
    async def transcribe(self, audio_data: bytes) -> Optional[str]:
        raise NotImplementedError


class WhisperAPI(STTProvider):
    """OpenAI Whisper API transcription"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client = None
        
    async def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key)
        return self._client
        
    async def transcribe(self, audio_data: bytes) -> Optional[str]:
        try:
            client = await self._get_client()
            
            file_like = io.BytesIO(audio_data)
            file_like.name = "audio.wav"
            
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=file_like
            )
            
            return response.text
            
        except Exception as e:
            log.error(f"Whisper API error: {e}")
            return None


class FasterWhisper(STTProvider):
    """Local Faster-Whisper transcription"""
    
    def __init__(self, model: str = "base"):
        self.model_name = model
        self._model = None
        self._sample_rate = 16000
        
    async def _get_model(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
                self._model = WhisperModel(self.model_name, device="cpu")
                log.info(f"🎙️ Faster-Whisper model loaded: {self.model_name}")
            except Exception as e:
                log.error(f"Failed to load Faster-Whisper: {e}")
                raise
        return self._model
        
    async def transcribe(self, audio_data: bytes) -> Optional[str]:
        try:
            model = await self._get_model()
            
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio_data)
                temp_path = f.name
                
            try:
                segments, _ = model.transcribe(temp_path)
                text = " ".join([s.text for s in segments])
                return text.strip() if text else None
            finally:
                Path(temp_path).unlink(missing_ok=True)
                
        except Exception as e:
            log.error(f"Faster-Whisper error: {e}")
            return None


class VoskSTT(STTProvider):
    """Offline Vosk speech recognition"""
    
    def __init__(self, model_path: str = "models/vosk"):
        self.model_path = model_path
        self._model = None
        self._recognizer = None
        
    async def _get_recognizer(self):
        if self._recognizer is None:
            try:
                import vosk
                
                model_dir = Path(self.model_path)
                if not model_dir.exists():
                    log.warning(f"🎙️ Vosk model not found at {self.model_path}")
                    return None
                    
                self._model = vosk.Model(str(model_dir))
                self._recognizer = vosk.KaldiRecognizer(self._model, 16000)
                log.info("🎙️ Vosk recognizer ready")
            except Exception as e:
                log.error(f"Failed to load Vosk: {e}")
                return None
        return self._recognizer
        
    async def transcribe(self, audio_data: bytes) -> Optional[str]:
        try:
            recognizer = await self._get_recognizer()
            if recognizer is None:
                return None
                
            if recognizer.AcceptWaveform(audio_data):
                import json
                result = json.loads(recognizer.Result())
                return result.get("text", "")
            return None
            
        except Exception as e:
            log.error(f"Vosk error: {e}")
            return None


class STTManager:
    """Manages STT providers and transcription"""
    
    def __init__(self, config):
        self.config = config
        self._provider: Optional[STTProvider] = None
        self._current_provider_name = None
        
    async def initialize(self):
        """Initialize STT manager"""
        log.info("🎙️ Initializing STT...")
        
        provider_type = self.config.get("ai.stt_provider", "whisper_api")
        
        if provider_type == "whisper_api":
            api_key = self.config.get_api_key("openai")
            if api_key:
                self._provider = WhisperAPI(api_key)
                self._current_provider_name = "whisper_api"
            else:
                log.warning("🎙️ No OpenAI API key for Whisper")
                
        elif provider_type == "faster_whisper":
            model = self.config.get("ai.whisper_model", "base")
            self._provider = FasterWhisper(model)
            self._current_provider_name = "faster_whisper"
            
        elif provider_type == "vosk":
            model_path = self.config.get("ai.vosk_model_path", "models/vosk")
            self._provider = VoskSTT(model_path)
            self._current_provider_name = "vosk"
            
        log.info(f"✅ STT ready using {self._current_provider_name}")
        
    async def transcribe(self, audio_data: bytes) -> Optional[str]:
        """Transcribe audio to text"""
        if self._provider is None:
            log.warning("🎙️ No STT provider initialized")
            return None
            
        try:
            text = await self._provider.transcribe(audio_data)
            if text:
                log.info(f"🎙️ Transcribed: {text[:50]}...")
            return text
        except Exception as e:
            log.error(f"🎙️ Transcription failed: {e}")
            return None
            
    async def transcribe_file(self, filepath: str) -> Optional[str]:
        """Transcribe audio file"""
        try:
            with open(filepath, 'rb') as f:
                audio_data = f.read()
            return await self.transcribe(audio_data)
        except Exception as e:
            log.error(f"🎙️ File transcription failed: {e}")
            return None
            
    def get_provider_name(self) -> str:
        """Get current provider name"""
        return self._current_provider_name or "none"
