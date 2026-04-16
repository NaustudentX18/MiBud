"""
MiBud - State Management
Manages the state machine for different operational modes
"""

import asyncio
from enum import Enum
from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
import time
import logging

log = logging.getLogger("MiBud")


class MiBudState(Enum):
    """MiBud operational states"""
    BOOTING = "booting"
    SETUP = "setup"
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    ERROR = "error"
    SLEEPING = "sleeping"
    SHUTTING_DOWN = "shutting_down"


class MiBudMode(Enum):
    """MiBud operational modes"""
    NORMAL = "normal"
    QUIET = "quiet"  # Whisper mode - no audio
    GUEST = "guest"
    CUSTOM = "custom"


@dataclass
class ConversationEntry:
    """Single conversation entry"""
    role: str  # user, assistant
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    provider: Optional[str] = None
    model: Optional[str] = None
    latency_ms: Optional[int] = None


class StateManager:
    """Manages MiBud state"""
    
    def __init__(self):
        self.current_state = MiBudState.IDLE
        self.current_mode = MiBudMode.NORMAL
        self.current_personality = "assistant"
        
        # Conversation
        self.conversation: list[ConversationEntry] = []
        self.max_conversation_length = 10
        
        # Timing
        self.last_activity = time.time()
        self.state_entered_at = time.time()
        
        # Audio levels
        self.current_volume = 50
        self.is_muted = False
        
        # Network
        self.is_online = True
        self.wifi_strength = 0
        
        # Battery
        self.battery_level = 100
        self.is_charging = False
        
        # Callbacks
        self.state_callbacks: list[Callable] = []

        # Auto-recovery settings
        self._error_recovery_timeout = 5.0  # seconds before auto-recovery
        self._recovery_task = None
        self._is_recovering = False
        
    async def initialize(self):
        """Initialize state"""
        self.set_state(MiBudState.IDLE)
        
    def get_state(self) -> str:
        """Return the current state as a string value"""
        return self.current_state.value

    def set_state(self, new_state):
        """Change state; accepts MiBudState enum or string value"""
        if isinstance(new_state, str):
            new_state = MiBudState(new_state)
        old_state = self.current_state
        self.current_state = new_state
        self.state_entered_at = time.time()
        
        # Notify callbacks
        for callback in self.state_callbacks:
            try:
                callback(old_state, new_state)
            except Exception as e:
                print(f"State callback error: {e}")

        # Auto-recovery from ERROR state
        if new_state == MiBudState.ERROR:
            self._is_recovering = True
            self._schedule_recovery()

    def _schedule_recovery(self):
        """Schedule automatic recovery from ERROR state."""
        if self._recovery_task is not None:
            self._recovery_task.cancel()
            self._recovery_task = None

        async def recovery_loop():
            await asyncio.sleep(self._error_recovery_timeout)
            if self.current_state == MiBudState.ERROR and self._is_recovering:
                old = self.current_state
                self.current_state = MiBudState.IDLE
                self.state_entered_at = time.time()
                log.info("Auto-recovering from ERROR to IDLE")
                for callback in self.state_callbacks:
                    try:
                        callback(old, self.current_state)
                    except Exception:
                        pass
                self._is_recovering = False

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running event loop — schedule via call_later
            loop = asyncio.get_event_loop()

        try:
            self._recovery_task = asyncio.create_task(recovery_loop())
        except RuntimeError:
            # Fallback for sync contexts: use call_later
            def sync_recovery():
                time.sleep(self._error_recovery_timeout)
                if self.current_state == MiBudState.ERROR and self._is_recovering:
                    old = self.current_state
                    self.current_state = MiBudState.IDLE
                    self.state_entered_at = time.time()
                    log.info("Auto-recovering from ERROR to IDLE")
                    for callback in self.state_callbacks:
                        try:
                            callback(old, self.current_state)
                        except Exception:
                            pass
                    self._is_recovering = False
            loop.call_later(self._error_recovery_timeout, sync_recovery)

    def cancel_recovery(self):
        """Cancel any pending error recovery."""
        if self._recovery_task:
            self._recovery_task.cancel()
            self._recovery_task = None
        self._is_recovering = False

    async def set_mode(self, new_mode: MiBudMode):
        """Change mode"""
        self.current_mode = new_mode
        
    def set_personality(self, personality: str):
        """Set current personality"""
        self.current_personality = personality
        self.update_activity()
        
    def add_conversation_entry(self, role: str, content: str, 
                              provider: str = None, model: str = None, 
                              latency_ms: int = None):
        """Add conversation entry"""
        entry = ConversationEntry(
            role=role,
            content=content,
            provider=provider,
            model=model,
            latency_ms=latency_ms
        )
        self.conversation.append(entry)
        
        # Trim if needed
        if len(self.conversation) > self.max_conversation_length:
            self.conversation = self.conversation[-self.max_conversation_length:]
            
        self.update_activity()
        
    def get_conversation_context(self, max_entries: int = 5) -> list[Dict]:
        """Get conversation context for AI"""
        entries = self.conversation[-max_entries:]
        return [{"role": e.role, "content": e.content} for e in entries]
        
    def clear_conversation(self):
        """Clear conversation history"""
        self.conversation = []
        
    def update_activity(self):
        """Update last activity timestamp"""
        self.last_activity = time.time()
        
    def is_idle(self, timeout: int = 60) -> bool:
        """Check if idle"""
        return (time.time() - self.last_activity) > timeout
        
    def get_state_duration(self) -> float:
        """Get seconds in current state"""
        return time.time() - self.state_entered_at
        
    def register_state_callback(self, callback: Callable):
        """Register state change callback"""
        self.state_callbacks.append(callback)
        
    # Status methods
    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive status"""
        return {
            "state": self.current_state.value,
            "mode": self.current_mode.value,
            "personality": self.current_personality,
            "battery": self.battery_level,
            "charging": self.is_charging,
            "online": self.is_online,
            "wifi_strength": self.wifi_strength,
            "muted": self.is_muted,
            "volume": self.current_volume,
            "conversation_length": len(self.conversation),
            "idle_seconds": int(time.time() - self.last_activity),
        }
