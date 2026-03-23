"""
MiBud - Conversation Manager
Handles the complete conversation flow: wake -> listen -> think -> speak
"""

import asyncio
import logging
from typing import Optional, Callable, List
from dataclasses import dataclass, field
from datetime import datetime

from ai.router import AIRouter, ChatMessage
from ai.stt import STTManager
from ai.tts import TTSManager
from personalities.presets import get_personality, Personality

log = logging.getLogger("MiBud")


@dataclass
class ConversationMessage:
    """A message in the conversation"""
    role: str  # user, assistant
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    audio_data: Optional[bytes] = None


class ConversationManager:
    """Manages the complete conversation flow"""
    
    def __init__(self, config, audio_manager, ai_router=None):
        self.config = config
        self.audio_manager = audio_manager
        self.ai_router = ai_router
        self.stt = STTManager(config)
        self.tts = TTSManager(config, audio_manager)
        
        self._is_active = False
        self._conversation_history: List[ConversationMessage] = []
        self._max_history = 50
        self._current_personality: Optional[Personality] = None
        self._callbacks: dict = {}
        
    async def initialize(self):
        """Initialize conversation manager"""
        log.info("💬 Initializing conversation manager...")
        
        await self.stt.initialize()
        await self.tts.initialize()
        
        if self.ai_router is None:
            self.ai_router = AIRouter(self.config)
            await self.ai_router.initialize()
            
        await self._load_personality()
        
        self._is_active = True
        log.info("✅ Conversation manager ready")
        
    async def _load_personality(self):
        """Load current personality"""
        personality_id = self.config.get("personality.current", "assistant")
        self._current_personality = get_personality(personality_id)
        
        if self._current_personality:
            log.info(f"💬 Loaded personality: {self._current_personality.name}")
            await self.tts.speak(self._current_personality.greeting, play=False)
            
    async def change_personality(self, personality_id: str):
        """Change to a different personality"""
        self._current_personality = get_personality(personality_id)
        self.config.set("personality.current", personality_id)
        self.config.save()
        
        if self._current_personality:
            log.info(f"💬 Changed personality to: {self._current_personality.name}")
            await self.tts.speak(self._current_personality.greeting)
            
    def _get_system_prompt(self) -> str:
        """Get system prompt for current personality"""
        if self._current_personality and self._current_personality.system_prompt:
            return self._current_personality.system_prompt
        return "You are MiBud, a helpful AI assistant. Keep responses concise and friendly."
        
    async def process_voice_input(self, audio_data: bytes) -> Optional[str]:
        """Process voice input: transcribe -> think -> speak"""
        if not self._is_active:
            return None
            
        self._emit("state_changed", "thinking")
        
        text = await self.stt.transcribe(audio_data)
        
        if not text:
            log.warning("💬 No speech detected")
            await self.tts.speak("Sorry, I didn't catch that", play=False)
            self._emit("state_changed", "idle")
            return None
            
        log.info(f"💬 User said: {text}")
        self._emit("user_speech", text)
        
        return await self.process_text_input(text)
        
    async def process_text_input(self, text: str) -> Optional[str]:
        """Process text input: think -> speak"""
        if not self._is_active:
            return None
            
        self._emit("state_changed", "thinking")
        
        self._conversation_history.append(
            ConversationMessage(role="user", content=text)
        )
        
        response = await self._generate_response(text)
        
        if response:
            self._conversation_history.append(
                ConversationMessage(role="assistant", content=response)
            )
            
            while len(self._conversation_history) > self._max_history:
                self._conversation_history.pop(0)
                
            self._emit("assistant_speech", response)
            
            await self.tts.speak(response)
            
        self._emit("state_changed", "idle")
        return response
        
    async def _generate_response(self, user_text: str) -> Optional[str]:
        """Generate AI response"""
        try:
            messages = [
                ChatMessage(role="system", content=self._get_system_prompt())
            ]
            
            for msg in self._conversation_history[-10:]:
                messages.append(ChatMessage(role=msg.role, content=msg.content))
                
            response = await self.ai_router.generate(
                prompt=user_text,
                context=messages
            )
            
            if response.error:
                log.error(f"💬 AI error: {response.error}")
                await self.tts.speak("Sorry, I had trouble thinking about that", play=False)
                return None
                
            log.info(f"💬 Response: {response.text[:50]}...")
            return response.text
            
        except Exception as e:
            log.error(f"💬 Response generation failed: {e}")
            return None
            
    async def listen_for_command(self, timeout: float = 10.0) -> Optional[str]:
        """Listen for a voice command with timeout"""
        if not self.audio_manager:
            return None
            
        self._emit("state_changed", "listening")
        
        try:
            import audioop
            
            audio_chunks = []
            silence_threshold = 500
            silence_count = 0
            max_silence = 30
            is_speaking = False
            
            device = self.audio_manager._get_recorder_device()
            if device is None:
                log.warning("💬 No audio device available")
                return None
                
            async def read_chunk():
                return device.read()
                
            while True:
                try:
                    _, data = await asyncio.wait_for(
                        asyncio.to_thread(read_chunk),
                        timeout=1.0
                    )
                    
                    if data:
                        rms = audioop.rms(data, 2)
                        
                        if rms > silence_threshold:
                            is_speaking = True
                            silence_count = 0
                            audio_chunks.append(data)
                        elif is_speaking:
                            silence_count += 1
                            if silence_count > max_silence:
                                break
                                
                except asyncio.TimeoutError:
                    if is_speaking:
                        break
                        
        except Exception as e:
            log.error(f"💬 Listen error: {e}")
            
        self._emit("state_changed", "idle")
        
        if len(audio_chunks) > 5:
            audio_data = b"".join(audio_chunks)
            return await self.process_voice_input(audio_data)
            
        return None
        
    def register_callback(self, event: str, callback: Callable):
        """Register callback for conversation events"""
        self._callbacks[event] = callback
        
    def _emit(self, event: str, data=None):
        """Emit an event to registered callbacks"""
        if event in self._callbacks:
            try:
                self._callbacks[event](data)
            except Exception as e:
                log.error(f"Callback error for {event}: {e}")
                
    def get_conversation_history(self) -> List[ConversationMessage]:
        """Get conversation history"""
        return self._conversation_history.copy()
        
    def clear_history(self):
        """Clear conversation history"""
        self._conversation_history.clear()
        
    async def stop(self):
        """Stop conversation manager"""
        self._is_active = False
        log.info("💬 Conversation manager stopped")
