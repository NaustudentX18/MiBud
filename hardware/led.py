"""
MiBud Hardware - LED Manager
RGB LED Control matching personality themes
"""

import os
import logging
import platform
from typing import Optional

log = logging.getLogger("MiBud")

# WhisPlay driver path
_WHISPLAY_DRIVER = "/home/pi/Whisplay/Driver"


class LEDManager:
    """Manages RGB LED on WhisPlay HAT"""
    
    # LED states
    STATE_OFF = "off"
    STATE_IDLE = "idle"
    STATE_LISTENING = "listening"
    STATE_THINKING = "thinking"
    STATE_SPEAKING = "speaking"
    STATE_ERROR = "error"
    
    # Colors (R, G, B)
    COLORS = {
        "white": (255, 255, 255),
        "red": (255, 0, 0),
        "green": (0, 255, 0),
        "blue": (0, 0, 255),
        "cyan": (0, 255, 255),
        "magenta": (255, 0, 255),
        "yellow": (255, 255, 0),
        "orange": (255, 165, 0),
        "purple": (128, 0, 128),
        "pink": (255, 192, 203),
        "off": (0, 0, 0),
    }
    
    def __init__(self):
        self.is_initialized = False
        self.is_rpi = platform.machine().startswith(('arm', 'aarch'))
        self._board = None
        self._gpio = None
        self._current_color = (0, 255, 0)  # Default green
        self._current_state = self.STATE_OFF
        self._brightness = 100
        self._animation_task = None
        self._is_animating = False
        
    async def initialize(self):
        """Initialize LED"""
        log.info("💡 Initializing LED...")
        
        if not self.is_rpi:
            log.info("💡 Non-RPi platform - simulation mode")
            self.is_initialized = True
            return
            
        try:
            # Try WhisPlay driver
            if os.path.exists(_WHISPLAY_DRIVER):
                sys.path.append(_WHISPLAY_DRIVER)
                try:
                    from WhisPlay import WhisPlayBoard
                    self._board = WhisPlayBoard()
                    log.info("💡 WhisPlay LED initialized")
                except ImportError:
                    pass
                    
            # Setup GPIO for direct control if needed
            try:
                import RPi.GPIO as GPIO
                self._gpio = GPIO
                # LED typically on GPIO 18 (PWM)
                self._led_pin = 18
                GPIO.setup(self._led_pin, GPIO.OUT)
                self._led_pwm = GPIO.PWM(self._led_pin, 100)
                self._led_pwm.start(0)
                log.info("💡 GPIO LED initialized")
            except ImportError:
                log.warning("💡 GPIO not available for LED")
                
        except Exception as e:
            log.warning(f"💡 LED init warning: {e}")
            
        self.is_initialized = True
        log.info("✅ LED initialized")
        
    def set_color(self, color: tuple):
        """Set LED color (R, G, B) 0-255"""
        self._current_color = tuple(max(0, min(255, c)) for c in color)
        self._update_led()
        
    def set_color_by_name(self, color_name: str):
        """Set LED color by name"""
        if color_name.lower() in self.COLORS:
            self.set_color(self.COLORS[color_name.lower()])
        else:
            log.warning(f"💡 Unknown color: {color_name}")
            
    def set_state(self, state: str):
        """Set LED state (idle, listening, thinking, speaking, error)"""
        self._current_state = state
        
        # Map states to colors
        state_colors = {
            self.STATE_OFF: "off",
            self.STATE_IDLE: "green",
            self.STATE_LISTENING: "cyan",
            self.STATE_THINKING: "yellow",
            self.STATE_SPEAKING: "green",
            self.STATE_ERROR: "red",
        }
        
        color_name = state_colors.get(state, "green")
        if color_name != "off":
            self.set_color_by_name(color_name)
            
    def set_brightness(self, level: int):
        """Set LED brightness (0-100)"""
        self._brightness = max(0, min(100, level))
        self._update_led()
        
    def _update_led(self):
        """Update LED with current color and brightness"""
        if not self.is_initialized:
            return
            
        if self._led_pwm:
            # Apply brightness
            r, g, b = self._current_color
            brightness = self._brightness / 100.0
            
            # PWM frequency for RGB is complex, simplified here
            duty_cycle = int(sum(self._current_color) / 3 * brightness)
            self._led_pwm.ChangeDutyCycle(duty_cycle)
            
        if self._board:
            try:
                # WhisPlay board may have its own LED control
                pass
            except Exception as e:
                log.debug(f"LED update: {e}")
                
    async def pulse(self, color: tuple = None, duration: float = 1.0, cycles: int = 1):
        """Pulse LED"""
        if color:
            original_color = self._current_color
            self.set_color(color)
            
        for _ in range(cycles):
            # Fade in
            for duty in range(0, 101, 10):
                self.set_brightness(duty)
                await asyncio.sleep(0.05)
            # Fade out
            for duty in range(100, -1, -10):
                self.set_brightness(duty)
                await asyncio.sleep(0.05)
                
        if color:
            self.set_color(original_color)
            
    async def rainbow_cycle(self, duration: float = 2.0):
        """Cycle through rainbow colors"""
        import colorsys
        
        steps = 20
        step_duration = duration / steps
        
        for i in range(steps):
            hue = i / steps
            rgb = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
            self.set_color(tuple(int(c * 255) for c in rgb))
            await asyncio.sleep(step_duration)
            
    async def blink(self, color: tuple = None, times: int = 3, interval: float = 0.3):
        """Blink LED"""
        if color:
            original_color = self._current_color
            
        for _ in range(times):
            self.set_color_by_name("off")
            await asyncio.sleep(interval)
            self.set_color(color or self._current_color)
            await asyncio.sleep(interval)
            
        if color:
            self.set_color(original_color)
            
    async def breathe(self, color: tuple = None, duration: float = 2.0):
        """Breathing/pulse animation"""
        if color:
            original_color = self._current_color
            
        import math
        steps = 20
        step_duration = duration / steps
        
        for i in range(steps * 2):
            # Sine wave for smooth breathing
            intensity = (math.sin(i * math.pi / steps) + 1) / 2
            if color:
                r, g, b = color
            else:
                r, g, b = self._current_color
            self.set_color((int(r * intensity), int(g * intensity), int(b * intensity)))
            await asyncio.sleep(step_duration)
            
        if color:
            self.set_color(original_color)
            
    async def cleanup(self):
        """Cleanup LED resources"""
        log.info("💡 LED cleanup")
        if self._led_pwm:
            self._led_pwm.stop()
        if self._gpio:
            try:
                self._gpio.cleanup()
            except:
                pass
