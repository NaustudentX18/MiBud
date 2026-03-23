"""
MiBud - Text-to-Speech (TTS)
Handles speech synthesis with multiple provider options
"""

import asyncio
import logging
import platform
from typing import Optional
from pathlib import Path

log = logging.getLogger("MiBud")


class TTSProvider:
    """Base TTS provider"""
    
    async def speak(self, text: str) -> Optional[bytes]:
        raise NotImplementedError


class OpenAITTS(TTSProvider):
    """OpenAI TTS synthesis"""
    
    def __init__(self, api_key: str, voice: str = "alloy"):
        self.api_key = api_key
        self.voice = voice
        self._client = None
        
    async def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key)
        return self._client
        
    async def speak(self, text: str) -> Optional[bytes]:
        try:
            client = await self._get_client()
            
            response = client.audio.speech.create(
                model="tts-1",
                voice=self.voice,
                input=text
            )
            
            return response.content
            
        except Exception as e:
            log.error(f"OpenAI TTS error: {e}")
            return None


class PiperTTS(TTSProvider):
    """Offline Piper TTS synthesis"""
    
    def __init__(self, model_path: str = "models/piper"):
        self.model_path = Path(model_path)
        self._process = None
        self._stdin = None
        self._stdout = None
        
    async def initialize(self):
        """Initialize Piper process"""
        try:
            import subprocess
            
            model_file = next(self.model_path.glob("*.onnx"), None)
            if not model_file:
                log.warning("🔊 Piper model not found")
                return
                
            config_file = model_file.with_suffix(".json")
            
            self._process = subprocess.Popen(
                ["piper", "--model", str(model_file), "--output-raw"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            log.info(f"🔊 Piper TTS ready: {model_file.name}")
            
        except Exception as e:
            log.warning(f"🔊 Piper init failed: {e}")
            
    async def speak(self, text: str) -> Optional[bytes]:
        if self._process is None:
            return None
            
        try:
            import struct
            
            text_bytes = (text + "\n").encode()
            self._process.stdin.write(text_bytes)
            self._process.stdin.flush()
            
            audio_chunks = []
            while True:
                try:
                    import select
                    if select.select([self._process.stdout], [], [], 1.0)[0]:
                        chunk = self._process.stdout.read(4096)
                        if not chunk:
                            break
                        audio_chunks.append(chunk)
                    else:
                        break
                except:
                    break
                    
            return b"".join(audio_chunks) if audio_chunks else None
            
        except Exception as e:
            log.error(f"Piper TTS error: {e}")
            return None
            
    async def cleanup(self):
        if self._process:
            self._process.terminate()


class CoquiTTS(TTSProvider):
    """Offline Coqui TTS"""
    
    def __init__(self):
        self._model = None
        self._speaker_id = None
        
    async def initialize(self):
        try:
            from TTS.api import TTS
            
            self._model = TTS(model_name="tts_models/en/ljspeech/tacotron2-DDC")
            log.info("🔊 Coqui TTS ready")
        except Exception as e:
            log.warning(f"🔊 Coqui init failed: {e}")
            
    async def speak(self, text: str) -> Optional[bytes]:
        if self._model is None:
            return None
            
        try:
            import numpy as np
            import scipy.io.wavfile as wavfile
            import io
            
            wav = self._model.tts(text)
            
            buffer = io.BytesIO()
            wavfile.write(buffer, samplerate=22050, data=wav)
            return buffer.getvalue()
            
        except Exception as e:
            log.error(f"Coqui TTS error: {e}")
            return None


class SystemTTS(TTSProvider):
    """System TTS (espeak/pyttsx3) - fallback"""
    
    def __init__(self):
        self._is_rpi = platform.machine().startswith(('arm', 'aarch'))
        
    async def speak(self, text: str) -> Optional[bytes]:
        if not self._is_rpi:
            log.info(f"🔊 [System TTS] {text[:50]}...")
            return None
            
        try:
            import subprocess
            subprocess.run(["espeak", text], check=True, capture_output=True)
            return None
        except Exception as e:
            log.error(f"System TTS error: {e}")
            return None


class Pyttsx3TTS(TTSProvider):
    """Offline pyttsx3 TTS"""
    
    def __init__(self):
        self._engine = None
        
    async def initialize(self):
        try:
            import pyttsx3
            self._engine = pyttsx3.init()
            log.info("🔊 pyttsx3 TTS ready")
        except Exception as e:
            log.warning(f"🔊 pyttsx3 init failed: {e}")
            
    async def speak(self, text: str) -> Optional[bytes]:
        if self._engine is None:
            return None
            
        try:
            import tempfile
            import os
            
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                temp_path = f.name
                
            self._engine.save_to_file(text, temp_path)
            self._engine.runAndWait()
            
            with open(temp_path, 'rb') as f:
                audio_data = f.read()
                
            os.unlink(temp_path)
            return audio_data
            
        except Exception as e:
            log.error(f"pyttsx3 TTS error: {e}")
            return None


class TTSManager:
    """Manages TTS providers and speech synthesis"""
    
    def __init__(self, config, audio_manager=None):
        self.config = config
        self.audio_manager = audio_manager
        self._provider: Optional[TTSProvider] = None
        self._current_provider_name = None
        self._is_speaking = False
        
    async def initialize(self):
        """Initialize TTS manager"""
        log.info("🔊 Initializing TTS...")
        
        provider_type = self.config.get("ai.tts_provider", "openai_tts")
        
        if provider_type == "openai_tts":
            api_key = self.config.get_api_key("openai")
            if api_key:
                voice = self.config.get("personality.voice", "alloy")
                self._provider = OpenAITTS(api_key, voice)
                self._current_provider_name = "openai_tts"
            else:
                log.warning("🔊 No OpenAI API key for TTS")
                
        elif provider_type == "piper":
            model_path = self.config.get("ai.piper_model_path", "models/piper")
            self._provider = PiperTTS(model_path)
            await self._provider.initialize()
            self._current_provider_name = "piper"
            
        elif provider_type == "coqui":
            self._provider = CoquiTTS()
            await self._provider.initialize()
            self._current_provider_name = "coqui"
            
        elif provider_type == "pyttsx3":
            self._provider = Pyttsx3TTS()
            await self._provider.initialize()
            self._current_provider_name = "pyttsx3"
            
        else:
            self._provider = SystemTTS()
            self._current_provider_name = "system"
            
        log.info(f"✅ TTS ready using {self._current_provider_name}")
        
    async def speak(self, text: str, play: bool = True) -> Optional[bytes]:
        """Speak text and optionally play audio"""
        if self._provider is None:
            log.warning("🔊 No TTS provider initialized")
            return None
            
        if self._is_speaking:
            log.info("🔊 Already speaking, skipping...")
            return None
            
        self._is_speaking = True
        
        try:
            log.info(f"🔊 Speaking: {text[:50]}...")
            
            audio_data = await self._provider.speak(text)
            
            if audio_data and play and self.audio_manager:
                await self.audio_manager.play_audio(audio_data)
                
            return audio_data
            
        except Exception as e:
            log.error(f"🔊 TTS speak error: {e}")
            return None
            
        finally:
            self._is_speaking = False
            
    async def speak_and_wait(self, text: str) -> bool:
        """Speak text and wait for completion"""
        await self.speak(text, play=True)
        return True
        
    def is_speaking(self) -> bool:
        """Check if currently speaking"""
        return self._is_speaking
        
    def get_provider_name(self) -> str:
        """Get current provider name"""
        return self._current_provider_name or "none"
