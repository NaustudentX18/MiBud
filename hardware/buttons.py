"""
MiBud Hardware - Button Manager
GPIO Button Handling with Long-press and Hold detection
"""

import os
import logging
import platform
import asyncio
from typing import Callable, Optional
from dataclasses import dataclass

log = logging.getLogger("MiBud")

# WhisPlay driver path
_WHISPLAY_DRIVER = "/home/pi/Whisplay/Driver"

@dataclass
class ButtonConfig:
    """Button configuration"""
    button_a_pin: int = 17  # GPIO 17 - Primary button
    button_b_pin: int = 27  # GPIO 27 - Secondary button
    long_press_threshold: float = 2.0  # seconds
    hold_threshold: float = 0.5  # seconds
    debounce_ms: int = 200


class ButtonManager:
    """Manages GPIO buttons for WhisPlay HAT"""
    
    def __init__(self, config: ButtonConfig = None):
        self.config = config or ButtonConfig()
        self.is_initialized = False
        self.is_rpi = platform.machine().startswith(('arm', 'aarch'))
        self._board = None
        self._gpio = None
        
        # Callbacks
        self._short_press_callback: Optional[Callable] = None
        self._long_press_callback: Optional[Callable] = None
        self._hold_callback: Optional[Callable] = None
        self._any_press_callback: Optional[Callable] = None
        
        # State tracking
        self._button_states = {17: False, 27: False}
        self._button_timestamps = {17: 0.0, 27: 0.0}
        
    async def initialize(self):
        """Initialize button handling"""
        log.info("🔘 Initializing buttons...")
        
        if not self.is_rpi:
            log.info("🔘 Non-RPi platform - simulation mode")
            self.is_initialized = True
            return
            
        try:
            # Try WhisPlay driver first
            if os.path.exists(_WHISPLAY_DRIVER):
                sys.path.append(_WHISPLAY_DRIVER)
                try:
                    from WhisPlay import WhisPlayBoard
                    self._board = WhisPlayBoard()
                    log.info("🔘 WhisPlay buttons initialized")
                except ImportError:
                    pass
                    
            # Setup GPIO if needed
            try:
                import RPi.GPIO as GPIO
                self._gpio = GPIO
                GPIO.setmode(GPIO.BCM)
                GPIO.setup(self.config.button_a_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                GPIO.setup(self.config.button_b_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                
                # Add event detection
                GPIO.add_event_detect(
                    self.config.button_a_pin,
                    GPIO.FALLING,
                    callback=self._on_button_a,
                    bouncetime=self.config.debounce_ms
                )
                GPIO.add_event_detect(
                    self.config.button_b_pin,
                    GPIO.FALLING,
                    callback=self._on_button_b,
                    bouncetime=self.config.debounce_ms
                )
                log.info("🔘 GPIO buttons initialized")
                
            except ImportError:
                log.warning("🔘 RPi.GPIO not available")
                
        except Exception as e:
            log.warning(f"🔘 Button init warning: {e}")
            
        self.is_initialized = True
        log.info("✅ Buttons initialized")
        
    def set_callbacks(self, 
                    on_short_press: Callable = None,
                    on_long_press: Callable = None,
                    on_press: Callable = None,
                    on_any_press: Callable = None):
        """Set button callbacks"""
        if on_short_press:
            self._short_press_callback = on_short_press
        if on_long_press:
            self._long_press_callback = on_long_press
        if on_press:
            self._hold_callback = on_press
        if on_any_press:
            self._any_press_callback = on_any_press
            
    def _on_button_a(self, channel: int):
        """Handle button A events"""
        self._handle_button_event("A")
        
    def _on_button_b(self, channel: int):
        """Handle button B events"""
        self._handle_button_event("B")
        
    def _handle_button_event(self, button_id: str):
        """Process button event with timing"""
        import time
        
        pin = 17 if button_id == "A" else 27
        current_state = self._gpio.input(pin) == GPIO.LOW if self._gpio else False
        
        now = time.time()
        
        if current_state and not self._button_states[pin]:
            # Button pressed
            self._button_states[pin] = True
            self._button_timestamps[pin] = now
            
            # Any press callback
            if self._any_press_callback:
                self._any_press_callback(button_id)
                
        elif not current_state and self._button_states[pin]:
            # Button released
            press_duration = now - self._button_timestamps[pin]
            self._button_states[pin] = False
            
            if press_duration >= self.config.long_press_threshold:
                # Long press
                if self._long_press_callback:
                    log.info(f"🔘 Button {button_id} LONG press ({press_duration:.1f}s)")
                    self._long_press_callback(button_id)
            else:
                # Short press
                if self._short_press_callback:
                    log.info(f"🔘 Button {button_id} SHORT press ({press_duration:.2f}s)")
                    self._short_press_callback(button_id)
                    
    def _on_button_hold(self, button_id: str):
        """Handle button hold (called repeatedly while held)"""
        if self._hold_callback:
            self._hold_callback(button_id)
            
    async def cleanup(self):
        """Cleanup button resources"""
        log.info("🔘 Button cleanup")
        if self._gpio:
            try:
                self._gpio.cleanup()
            except:
                pass
