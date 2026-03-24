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
        self.current_state = MiBudState.BOOTING
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
        
    async def initialize(self):
        """Initialize state"""
        await self.set_state(MiBudState.IDLE)
        
    async def set_state(self, new_state: MiBudState):
        """Change state"""
        old_state = self.current_state
        self.current_state = new_state
        self.state_entered_at = time.time()
        
        # Notify callbacks
        for callback in self.state_callbacks:
            try:
                callback(old_state, new_state)
            except Exception as e:
                print(f"State callback error: {e}")
                
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
