"""
MiBud - Event System
Simple event bus for inter-component communication
"""

import asyncio
from typing import Dict, List, Callable, Any, Set
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict
import logging

log = logging.getLogger("MiBud")


@dataclass
class Event:
    """Event object"""
    name: str
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = "system"


class EventBus:
    """Simple async event bus"""
    
    def __init__(self):
        self.listeners: Dict[str, List[Callable]] = defaultdict(list)
        self.event_history: List[Event] = []
        self.max_history = 100
        self.running = False
        
    def on(self, event_name: str, callback: Callable):
        """Register event listener"""
        self.listeners[event_name].append(callback)
        return callback
        
    def off(self, event_name: str, callback: Callable):
        """Unregister event listener"""
        if callback in self.listeners[event_name]:
            self.listeners[event_name].remove(callback)
            
    def once(self, event_name: str, callback: Callable):
        """Register one-time listener"""
        async def wrapper(event: Event):
            await callback(event)
            self.off(event_name, wrapper)
            
        self.on(event_name, wrapper)
        
    async def emit(self, event_name: str, data: Dict[str, Any] = None, 
                   source: str = "system"):
        """Emit event"""
        event = Event(
            name=event_name,
            data=data or {},
            source=source
        )
        
        # Store in history
        self.event_history.append(event)
        if len(self.event_history) > self.max_history:
            self.event_history = self.event_history[-self.max_history:]
            
        # Notify listeners
        listeners = self.listeners.get(event_name, [])
        listeners.extend(self.listeners.get("*", []))  # Wildcard listeners
        
        for callback in listeners:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event)
                else:
                    callback(event)
            except Exception as e:
                log.error(f"Event callback error for {event_name}: {e}")
                
    def dispatch(self, event_name: str, data: Dict[str, Any] = None,
                source: str = "system"):
        """Synchronous emit (for non-async contexts)"""
        asyncio.create_task(self.emit(event_name, data, source))
        
    async def process_events(self):
        """Process pending events (can be called in main loop)"""
        # This is a placeholder - events are processed immediately on emit
        pass
        
    def get_history(self, event_name: str = None, limit: int = 10) -> List[Event]:
        """Get event history"""
        if event_name:
            events = [e for e in self.event_history if e.name == event_name]
        else:
            events = self.event_history
            
        return events[-limit:]
        
    def clear_history(self):
        """Clear event history"""
        self.event_history = []


# Predefined event names
class Events:
    """Event name constants"""
    # Button events
    BUTTON_PRESS = "button_press"
    BUTTON_LONG_PRESS = "button_long_press"
    BUTTON_HOLD = "button_hold"
    
    # Voice events
    WAKE_WORD_DETECTED = "wake_word_detected"
    LISTENING_START = "listening_start"
    LISTENING_STOP = "listening_stop"
    SPEECH_DETECTED = "speech_detected"
    SPEECH_END = "speech_end"
    TRANSCRIPTION_COMPLETE = "transcription_complete"
    
    # AI events
    AI_REQUEST = "ai_request"
    AI_RESPONSE = "ai_response"
    AI_ERROR = "ai_error"
    PROVIDER_SWITCH = "provider_switch"
    
    # State events
    STATE_CHANGE = "state_change"
    MODE_CHANGE = "mode_change"
    PERSONALITY_CHANGE = "personality_change"
    
    # Display events
    DISPLAY_UPDATE = "display_update"
    ANIMATION_START = "animation_start"
    ANIMATION_STOP = "animation_stop"
    
    # System events
    BOOT_COMPLETE = "boot_complete"
    SETUP_COMPLETE = "setup_complete"
    SHUTDOWN_START = "shutdown_start"
    ERROR = "error"
    
    # Hardware events
    BATTERY_LOW = "battery_low"
    BATTERY_CHARGING = "battery_charging"
    WIFI_CONNECTED = "wifi_connected"
    WIFI_DISCONNECTED = "wifi_disconnected"
    
    # Timer events
    TIMER_START = "timer_start"
    TIMER_COMPLETE = "timer_complete"
    ALARM_TRIGGER = "alarm_trigger"
