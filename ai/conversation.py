"""
MiBud - Conversation Manager
Handles the complete conversation flow: wake -> listen -> think -> speak

v2 additions:
- Long-term memory + fact extraction (ai/memory.py)
- Tool use in the router
- Optional streaming LLM -> sentence TTS
- Token-aware history trimming
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from ai.router import AIRouter, ChatMessage
from ai.stt import STTManager
from ai.tts import TTSManager
from personalities.presets import Personality, get_personality

log = logging.getLogger("MiBud")


@dataclass
class ConversationMessage:
    role: str  # user, assistant, tool
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    audio_data: Optional[bytes] = None


class ConversationManager:
    """Orchestrates listen -> think -> speak with memory and tools."""

    def __init__(
        self,
        config,
        audio_manager,
        ai_router: Optional[AIRouter] = None,
        memory=None,
        tool_context=None,
    ):
        self.config = config
        self.audio_manager = audio_manager
        self.ai_router = ai_router
        self.stt = STTManager(config)
        self.tts = TTSManager(config, audio_manager)

        self._is_active = False
        self._is_busy = False
        self._conversation_history: List[ConversationMessage] = []
        self._max_history = config.get("tuning.conversation_max_history", 10)
        self._current_personality: Optional[Personality] = None
        self._callbacks: Dict[str, Callable] = {}

        # Memory + tools
        self.memory = memory
        self._tool_ctx = tool_context
        self._fact_extractor = None
        self._tools_enabled = bool(config.get("features.enable_tools", True))
        self._streaming_enabled = bool(config.get("features.enable_streaming", True))
        self._tool_names: List[str] = []

    async def initialize(self):
        log.info("💬 Initializing conversation manager...")

        await self.stt.initialize()
        await self.tts.initialize()

        if self.ai_router is None:
            self.ai_router = AIRouter(self.config)
            await self.ai_router.initialize()

        # Tools: register built-ins if we have a context.
        if self._tool_ctx is not None and self._tools_enabled:
            from ai.tools import build_builtin_tools, get_registry
            reg = build_builtin_tools(self._tool_ctx)
            self.ai_router.attach_tools(reg)
            self._tool_names = reg.names()
            log.info(f"🛠️  {len(self._tool_names)} tools registered")

        # Memory: wire up fact extractor + summariser
        if self.memory is not None:
            from ai.memory import FactExtractor
            self._fact_extractor = FactExtractor(self.memory)
            async def _summarise(transcript: str) -> str:
                if self.ai_router is None:
                    return ""
                prompt = (
                    "Summarise the following conversation in one sentence from the "
                    "user's point of view. Focus on decisions, facts, and outcomes.\n\n"
                    + transcript
                )
                try:
                    resp = await self.ai_router.generate(prompt, context=None)
                    return resp.text
                except Exception:
                    return ""
            self.memory._summarizer = _summarise  # type: ignore[attr-defined]

        await self._load_personality()

        self._is_active = True
        log.info("✅ Conversation manager ready")

    async def _load_personality(self):
        personality_id = self.config.get("personality.current", "assistant")
        self._current_personality = get_personality(personality_id)
        if self._current_personality:
            log.info(f"💬 Loaded personality: {self._current_personality.name}")
            await self.tts.speak(self._current_personality.greeting, play=False)

    async def change_personality(self, personality_id: str):
        self._current_personality = get_personality(personality_id)
        self.config.set("personality.current", personality_id)
        self.config.save()
        if self._current_personality:
            log.info(f"💬 Changed personality to: {self._current_personality.name}")
            await self.tts.speak(self._current_personality.greeting)

    async def _build_system_prompt(self, user_text: str = "") -> str:
        base = (
            self._current_personality.system_prompt
            if self._current_personality and self._current_personality.system_prompt
            else "You are MiBud, a helpful AI assistant. Keep responses concise and friendly."
        )
        extras: List[str] = [base]
        if self.memory is not None:
            try:
                block = await self.memory.build_context_block(user_text, k=4)
                if block:
                    extras.append(block)
            except Exception as e:
                log.debug(f"memory context unavailable: {e}")
        if self._tools_enabled and self._tool_names:
            extras.append(
                "You may call tools to answer. Prefer calling a tool over "
                "guessing for anything involving the current time, battery, "
                "timers, reminders, the camera, the user's memory, or home "
                "automation."
            )
        return "\n\n".join(extras)

    # ---- Public entry points ----------------------------------------

    async def process_voice_input(self, audio_data: bytes) -> Optional[str]:
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

    async def process_text_input(self, text: str, speak: bool = True) -> Optional[str]:
        if not self._is_active:
            return None
        self._is_busy = True
        self._emit("state_changed", "thinking")

        self._conversation_history.append(ConversationMessage(role="user", content=text))
        if self.memory is not None:
            self.memory.add_turn("user", text)
            if self._fact_extractor is not None:
                try:
                    await self._fact_extractor.extract(text)
                except Exception as e:
                    log.debug(f"fact extraction skipped: {e}")

        try:
            if speak and self._streaming_enabled:
                response_text = await self._generate_and_stream_speak(text)
            else:
                response = await self._generate_response(text)
                response_text = response.text if response else None
                if speak and response_text:
                    await self.tts.speak(response_text)

            if response_text:
                self._conversation_history.append(
                    ConversationMessage(role="assistant", content=response_text)
                )
                if self.memory is not None:
                    self.memory.add_turn("assistant", response_text)
                while len(self._conversation_history) > self._max_history:
                    self._conversation_history.pop(0)
                self._emit("assistant_speech", response_text)

            return response_text
        finally:
            self._emit("state_changed", "idle")
            self._is_busy = False

    # ---- Generation variants ----------------------------------------

    async def _build_messages(self, user_text: str) -> List[ChatMessage]:
        messages: List[ChatMessage] = [
            ChatMessage(role="system", content=await self._build_system_prompt(user_text))
        ]
        for msg in self._conversation_history[-self._max_history :]:
            if msg.role in ("user", "assistant"):
                messages.append(ChatMessage(role=msg.role, content=msg.content))
        return messages

    async def _generate_response(self, user_text: str):
        try:
            messages = await self._build_messages(user_text)
            response = await self.ai_router.generate(
                prompt=user_text,
                context=messages,
                tools=self._tool_names if self._tools_enabled else None,
            )
            if response.error:
                log.error(f"💬 AI error: {response.error}")
                await self.tts.speak("Sorry, I had trouble thinking about that", play=False)
                return None
            log.info(f"💬 Response ({response.provider}/{response.model}, {response.latency_ms}ms): {response.text[:80]}...")
            return response
        except Exception as e:
            log.error(f"💬 Response generation failed: {e}")
            return None

    async def _generate_and_stream_speak(self, user_text: str) -> Optional[str]:
        """Stream LLM output sentence-by-sentence into the speaker.

        Falls back to non-streaming generate() if no streaming provider is
        available or an exception is raised mid-stream.
        """
        from ai.streaming import stream_to_speech

        try:
            messages = await self._build_messages(user_text)
            iterator = self.ai_router.generate_stream(
                prompt=user_text,
                context=messages,
            )
            def _on_sentence(sentence: str) -> None:
                self._emit("assistant_partial", sentence)
            text, stats = await stream_to_speech(
                iterator,
                self.tts,
                on_sentence=_on_sentence,
            )
            if stats.first_sentence_ms is not None:
                log.info(f"💬 First sentence in {stats.first_sentence_ms}ms ({stats.total_sentences} sentences)")
            if not text.strip():
                # Streaming produced nothing — fall back to plain path with tools.
                response = await self._generate_response(user_text)
                if response is None:
                    return None
                await self.tts.speak(response.text)
                return response.text
            return text
        except Exception as e:
            log.warning(f"stream path failed, falling back: {e}")
            response = await self._generate_response(user_text)
            if response is None:
                return None
            await self.tts.speak(response.text)
            return response.text

    # ---- Listening --------------------------------------------------

    async def listen_for_command(self, timeout: float = 10.0) -> Optional[str]:
        if not self.audio_manager:
            return None
        self._emit("state_changed", "listening")
        audio_chunks: List[bytes] = []
        try:
            from utils.audio_utils import rms_level

            silence_threshold = self.config.get("tuning.stt_silence_threshold", 500)
            max_silence = self.config.get("tuning.stt_max_silence_chunks", 30)
            silence_count = 0
            is_speaking = False

            device = self.audio_manager._get_recorder_device()
            if device is None:
                log.warning("💬 No audio device available")
                return None

            def read_chunk():
                return device.read()

            while True:
                try:
                    _, data = await asyncio.wait_for(asyncio.to_thread(read_chunk), timeout=1.0)
                    if data:
                        rms = rms_level(data, 2)
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

    # ---- Callbacks --------------------------------------------------

    def register_callback(self, event: str, callback: Callable):
        self._callbacks[event] = callback

    def _emit(self, event: str, data=None):
        if event in self._callbacks:
            try:
                self._callbacks[event](data)
            except Exception as e:
                log.error(f"Callback error for {event}: {e}")

    # ---- State / accessors ------------------------------------------

    def is_busy(self) -> bool:
        return self._is_busy or self.tts.is_speaking()

    def get_conversation_history(self) -> List[ConversationMessage]:
        return self._conversation_history.copy()

    def clear_history(self):
        self._conversation_history.clear()

    async def stop(self):
        self._is_active = False
        if self.memory is not None:
            try:
                await self.memory.end_session()
            except Exception as e:
                log.debug(f"memory end_session failed: {e}")
        log.info("💬 Conversation manager stopped")
