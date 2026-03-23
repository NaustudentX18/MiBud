"""
MiBud Hardware - Display Driver
WhisPlay HAT ST7789 240x280 Display with Beautiful Animations
"""

import os
import sys
import time
import logging
import platform
from typing import Optional
from pathlib import Path
from datetime import datetime

try:
    from PIL import Image, ImageDraw, ImageFont
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

log = logging.getLogger("MiBud")

# WhisPlay paths
_WHISPLAY_DRIVER = "/home/pi/Whisplay/Driver"

# Display dimensions (240x280 for WhisPlay HAT)
WIDTH = 240
HEIGHT = 280

# Font paths
_FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
_FONT_REGULAR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
_FONT_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

# Color palettes per personality
THEMES = {
    "assistant": {
        "bg": "#1a1a2e", "fg": "#e0e0e0", 
        "accent": "#00ff64", "secondary": "#0096ff",
        "error": "#ff4757", "warning": "#ffa502"
    },
    "chef": {
        "bg": "#2d132c", "fg": "#ffeaa7",
        "accent": "#e94560", "secondary": "#fab1a0",
        "error": "#ff4757", "warning": "#ffa502"
    },
    "hacker": {
        "bg": "#000000", "fg": "#00ff00",
        "accent": "#00ff00", "secondary": "#008800",
        "error": "#ff0000", "warning": "#ffff00"
    },
    "dj": {
        "bg": "#1a1a2e", "fg": "#ffffff",
        "accent": "#e94560", "secondary": "#00d4ff",
        "error": "#ff4757", "warning": "#ffa502"
    },
    "mentor": {
        "bg": "#1e3a5f", "fg": "#dfe6e9",
        "accent": "#4da6ff", "secondary": "#74b9ff",
        "error": "#ff4757", "warning": "#fdcb6e"
    },
    "therapist": {
        "bg": "#2d3436", "fg": "#dfe6e9",
        "accent": "#74b9ff", "secondary": "#a29bfe",
        "error": "#ff7675", "warning": "#ffeaa7"
    },
    "nurse": {
        "bg": "#2c3e50", "fg": "#ffffff",
        "accent": "#ff7675", "secondary": "#fab1a0",
        "error": "#e74c3c", "warning": "#f39c12"
    },
    "teacher": {
        "bg": "#2c3e50", "fg": "#f1c40f",
        "accent": "#3498db", "secondary": "#f1c40f",
        "error": "#e74c3c", "warning": "#f39c12"
    },
    "comedian": {
        "bg": "#6c5ce7", "fg": "#ffffff",
        "accent": "#fd79a8", "secondary": "#a29bfe",
        "error": "#ff4757", "warning": "#ffeaa7"
    },
    "news_anchor": {
        "bg": "#2c3e50", "fg": "#ecf0f1",
        "accent": "#e74c3c", "secondary": "#3498db",
        "error": "#c0392b", "warning": "#f39c12"
    },
    "pilot": {
        "bg": "#34495e", "fg": "#95a5a6",
        "accent": "#3498db", "secondary": "#ecf0f1",
        "error": "#e74c3c", "warning": "#f1c40f"
    },
    "drill_sergeant": {
        "bg": "#c0392b", "fg": "#ffffff",
        "accent": "#f1c40f", "secondary": "#e74c3c",
        "error": "#2c3e50", "warning": "#f39c12"
    },
    "librarian": {
        "bg": "#4a4a4a", "fg": "#d4a574",
        "accent": "#d4a574", "secondary": "#8b8b8b",
        "error": "#ff4757", "warning": "#ffa502"
    },
    "detective": {
        "bg": "#2c2c2c", "fg": "#f39c12",
        "accent": "#f39c12", "secondary": "#5d5d5d",
        "error": "#e74c3c", "warning": "#f1c40f"
    },
    "scientist": {
        "bg": "#1a1a2e", "fg": "#dfe6e9",
        "accent": "#00cec9", "secondary": "#4a90e2",
        "error": "#ff4757", "warning": "#fdcb6e"
    },
    "artist": {
        "bg": "#d63031", "fg": "#ffffff",
        "accent": "#fdcb6e", "secondary": "#e17055",
        "error": "#2d3436", "warning": "#fab1a0"
    },
    "historian": {
        "bg": "#5d4e37", "fg": "#b8a082",
        "accent": "#b8a082", "secondary": "#8b7355",
        "error": "#ff4757", "warning": "#ffa502"
    },
    "explorer": {
        "bg": "#00b894", "fg": "#ffffff",
        "accent": "#55efc4", "secondary": "#00cec9",
        "error": "#d63031", "warning": "#fdcb6e"
    },
    "companion": {
        "bg": "#2d3436", "fg": "#dfe6e9",
        "accent": "#ff7675", "secondary": "#a29bfe",
        "error": "#d63031", "warning": "#ffeaa7"
    },
    "custom": {
        "bg": "#1a1a2e", "fg": "#e0e0e0",
        "accent": "#00ff64", "secondary": "#0096ff",
        "error": "#ff4757", "warning": "#ffa502"
    }
}


class Display:
    """WhisPlay HAT Display Manager with Beautiful Animations"""
    
    def __init__(self, brightness: int = 70):
        self.brightness = brightness
        self.is_initialized = False
        self.is_sleeping = False
        self.current_theme = "assistant"
        self.current_state = "idle"
        self._board = None
        self._image = None
        self._draw = None
        self.is_rpi = platform.machine().startswith(('arm', 'aarch'))
        
        # Animation state
        self._animation_frame = 0
        self._last_animation_update = 0
        
    async def initialize(self):
        """Initialize display"""
        log.info("📺 Initializing display...")
        
        if not _HAS_PIL:
            log.warning("PIL not available - display simulation mode")
            self.is_initialized = True
            return
            
        if not self.is_rpi:
            log.info("📺 Non-RPi platform - simulation mode")
            self.is_initialized = True
            return
            
        try:
            # Try to load WhisPlay driver
            if os.path.exists(_WHISPLAY_DRIVER):
                sys.path.append(_WHISPLAY_DRIVER)
                from WhisPlay import WhisPlayBoard
                self._board = WhisPlayBoard()
                self._board.lcd_set_brightness(brightness)
                log.info("📺 WhisPlay board initialized")
            else:
                log.warning("📺 WhisPlay driver not found - simulation mode")
                
        except Exception as e:
            log.warning(f"📺 Display init warning: {e}")
            
        # Create canvas
        self._image = Image.new('RGB', (WIDTH, HEIGHT), color=self._hex_to_rgb(THEMES["assistant"]["bg"]))
        self._draw = ImageDraw.Draw(self._image)
        
        self.is_initialized = True
        log.info("✅ Display initialized")
        
    def _hex_to_rgb(self, hex_color: str) -> tuple:
        """Convert hex color to RGB tuple"""
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    
    def _get_theme(self) -> dict:
        """Get current theme colors"""
        return THEMES.get(self.current_theme, THEMES["assistant"])
    
    def set_theme(self, theme_name: str):
        """Set display theme"""
        if theme_name in THEMES:
            self.current_theme = theme_name
            log.info(f"🎨 Theme set to: {theme_name}")
            
    def set_brightness(self, level: int):
        """Set display brightness (0-100)"""
        self.brightness = max(0, min(100, level))
        if self._board:
            self._board.lcd_set_brightness(self.brightness)
            
    def clear(self):
        """Clear display"""
        theme = self._get_theme()
        self._draw.rectangle([0, 0, WIDTH, HEIGHT], fill=theme["bg"])
        
    async def show_boot_animation(self):
        """Show boot animation"""
        theme = self._get_theme()
        
        for i in range(50):
            self.clear()
            
            # Loading bar
            bar_width = int((i / 50) * (WIDTH - 40))
            self._draw.rectangle([20, HEIGHT//2 - 10, WIDTH - 20, HEIGHT//2 + 10], 
                                fill=theme["secondary"])
            self._draw.rectangle([20, HEIGHT//2 - 10, 20 + bar_width, HEIGHT//2 + 10], 
                                fill=theme["accent"])
            
            # Logo text
            self._draw.text((WIDTH//2, HEIGHT//2 - 40), "MiBud", 
                           fill=theme["accent"], anchor="mm")
            
            self._update()
            await asyncio.sleep(0.05)
            
    async def show_idle(self, clock: str = None, date: str = None, 
                       battery: int = 100, wifi: int = 4):
        """Show idle screen with clock, date, battery, wifi"""
        theme = self._get_theme()
        
        self.clear()
        
        # Status bar
        self._draw.text((5, 5), f"🔋{battery}%", fill=theme["fg"])
        wifi_bars = "📶" + "▂▄▆█▇▉"[:wifi] if wifi > 0 else "📶✗"
        self._draw.text((WIDTH - 50, 5), wifi_bars, fill=theme["fg"])
        
        # Clock
        if clock is None:
            clock = datetime.now().strftime("%I:%M %p")
        if date is None:
            date = datetime.now().strftime("%b %d, %Y")
            
        # Large clock
        self._draw.text((WIDTH//2, 80), clock, fill=theme["accent"], 
                        font=ImageFont.truetype(_FONT_BOLD, 32), anchor="mm")
        
        # Date
        self._draw.text((WIDTH//2, 120), date, fill=theme["fg"],
                        font=ImageFont.truetype(_FONT_REGULAR, 12), anchor="mm")
        
        # Center box with MiBud info
        box_y = 150
        self._draw.rounded_rectangle([30, box_y, WIDTH-30, box_y+70], radius=10, 
                                    fill=theme["secondary"])
        self._draw.text((WIDTH//2, box_y + 20), "🤖 MiBud", fill=theme["bg"],
                        font=ImageFont.truetype(_FONT_BOLD, 16), anchor="mm")
        self._draw.text((WIDTH//2, box_y + 45), f"[{self.current_theme.title()}]", 
                        fill=theme["bg"], font=ImageFont.truetype(_FONT_REGULAR, 11), anchor="mm")
        
        # Wake instruction
        if not self.is_sleeping:
            self._draw.text((WIDTH//2, HEIGHT - 30), '🗣️ Say "Hey MiBud" or press button',
                           fill=theme["fg"], font=ImageFont.truetype(_FONT_REGULAR, 9), anchor="mm")
        
        self._update()
        self.current_state = "idle"
        
    async def show_listening(self, waveform: list = None):
        """Show listening state with waveform"""
        theme = self._get_theme()
        
        self.clear()
        
        # Header
        self._draw.text((WIDTH//2, 30), "🎤 LISTENING 🎤", fill=theme["accent"],
                        font=ImageFont.truetype(_FONT_BOLD, 16), anchor="mm")
        
        # Waveform visualization
        if waveform is None:
            # Animated placeholder waveform
            import math
            waveform = [math.sin((i + self._animation_frame) * 0.3) * 20 + 30 for i in range(20)]
            
        bar_width = 8
        spacing = 2
        start_x = (WIDTH - (bar_width + spacing) * 20) // 2
        max_height = 60
        
        for i, height in enumerate(waveform):
            bar_height = abs(height)
            x = start_x + i * (bar_width + spacing)
            y_center = HEIGHT // 2
            
            self._draw.rectangle([x, y_center - bar_height, x + bar_width, y_center + bar_height],
                               fill=theme["accent"])
        
        # Instruction
        self._draw.text((WIDTH//2, HEIGHT - 50), '🛑 Release to send',
                       fill=theme["fg"], font=ImageFont.truetype(_FONT_REGULAR, 11), anchor="mm")
        
        self._update()
        self.current_state = "listening"
        
    async def show_thinking(self, message: str = "Thinking..."):
        """Show thinking/processing state"""
        theme = self._get_theme()
        
        self.clear()
        
        # Header
        self._draw.text((WIDTH//2, 30), "🤔 THINKING...", fill=theme["accent"],
                        font=ImageFont.truetype(_FONT_BOLD, 16), anchor="mm")
        
        # Animated spinner
        spinner_frames = ["◐", "◑", "◒", "◓"]
        frame = spinner_frames[self._animation_frame % 4]
        
        # Draw spinning circles
        import math
        for i in range(8):
            angle = (self._animation_frame * 5 + i * 45) * math.pi / 180
            x = WIDTH//2 + int(math.cos(angle) * 50)
            y = HEIGHT//2 + int(math.sin(angle) * 50)
            size = 4 + (i % 3)
            self._draw.ellipse([x-size, y-size, x+size, y+size], fill=theme["accent"])
        
        # Center icon
        self._draw.text((WIDTH//2, HEIGHT//2), frame, fill=theme["fg"],
                        font=ImageFont.truetype(_FONT_BOLD, 32), anchor="mm")
        
        # Message
        if message:
            self._draw.text((WIDTH//2, HEIGHT//2 + 50), message[:30], fill=theme["fg"],
                            font=ImageFont.truetype(_FONT_REGULAR, 10), anchor="mm")
        
        self._update()
        self.current_state = "thinking"
        
    async def show_speaking(self, text: str = "", provider: str = ""):
        """Show speaking/response state"""
        theme = self._get_theme()
        
        self.clear()
        
        # Header
        self._draw.text((WIDTH//2, 25), "🔊 SPEAKING 🔊", fill=theme["accent"],
                        font=ImageFont.truetype(_FONT_BOLD, 14), anchor="mm")
        
        # Speaker animation bars
        bars = [20, 35, 50, 35, 20, 35, 50, 35, 20]
        bar_width = 12
        spacing = 4
        start_x = (WIDTH - (bar_width + spacing) * 9) // 2
        
        for i, height in enumerate(bars):
            x = start_x + i * (bar_width + spacing)
            y_center = 70
            # Use animation to vary heights
            animated_height = height + (10 if (self._animation_frame + i) % 3 == 0 else 0)
            self._draw.rectangle([x, y_center - animated_height//2, 
                                 x + bar_width, y_center + animated_height//2],
                                fill=theme["accent"])
        
        # Response text with word wrap
        if text:
            words = text.split()
            lines = []
            current_line = ""
            max_width = WIDTH - 30
            
            for word in words:
                test_line = current_line + " " + word if current_line else word
                # Approximate width check
                if len(test_line) < 25:
                    current_line = test_line
                else:
                    if current_line:
                        lines.append(current_line)
                    current_line = word
            if current_line:
                lines.append(current_line)
                
            # Display lines (first 6)
            y_pos = 100
            for line in lines[:6]:
                self._draw.text((15, y_pos), line, fill=theme["fg"],
                              font=ImageFont.truetype(_FONT_REGULAR, 10))
                y_pos += 16
                
            if len(lines) > 6:
                self._draw.text((15, y_pos), "...", fill=theme["secondary"],
                              font=ImageFont.truetype(_FONT_REGULAR, 10))
                
        # Provider info
        if provider:
            self._draw.text((WIDTH//2, HEIGHT - 20), f"via {provider}", fill=theme["secondary"],
                          font=ImageFont.truetype(_FONT_REGULAR, 8), anchor="mm")
          
        self._update()
        self.current_state = "speaking"
        
    async def show_error(self, message: str = "Error occurred"):
        """Show error state"""
        theme = self._get_theme()
        
        self.clear()
        
        # Red error background
        self._draw.rectangle([0, 0, WIDTH, HEIGHT], fill="#2d1f1f")
        
        # Error icon
        self._draw.text((WIDTH//2, 60), "❌", fill="#ff4757",
                        font=ImageFont.truetype(_FONT_BOLD, 48), anchor="mm")
        
        # Error text
        self._draw.text((WIDTH//2, 130), "ERROR", fill="#ff4757",
                        font=ImageFont.truetype(_FONT_BOLD, 20), anchor="mm")
        
        self._draw.text((WIDTH//2, 160), message[:30], fill="#ffffff",
                        font=ImageFont.truetype(_FONT_REGULAR, 11), anchor="mm")
        
        # Retry instruction
        self._draw.text((WIDTH//2, HEIGHT - 40), "Try again or press button",
                       fill="#aaaaaa", font=ImageFont.truetype(_FONT_REGULAR, 9), anchor="mm")
        
        self._update()
        self.current_state = "error"
        
    async def show_sleep(self):
        """Show sleep/idle screen"""
        theme = self._get_theme()
        
        self.clear()
        
        # Dim display
        bg_color = tuple(int(c * 0.2) for c in self._hex_to_rgb(theme["bg"]))
        self._draw.rectangle([0, 0, WIDTH, HEIGHT], fill=bg_color)
        
        # Clock
        clock = datetime.now().strftime("%I:%M")
        self._draw.text((WIDTH//2, HEIGHT//2 - 20), clock, fill=theme["secondary"],
                        font=ImageFont.truetype(_FONT_BOLD, 36), anchor="mm")
        
        # Zzz
        self._draw.text((WIDTH//2, HEIGHT//2 + 30), "Z z z", fill=theme["secondary"],
                        font=ImageFont.truetype(_FONT_REGULAR, 16), anchor="mm")
        
        self.is_sleeping = True
        self._update()
        self.current_state = "sleeping"
        
    async def show_personality_selector(self, personalities: list, selected: int = 0):
        """Show personality selection screen"""
        theme = self._get_theme()
        
        self.clear()
        
        # Header
        self._draw.text((WIDTH//2, 20), "👤 PERSONALITY", fill=theme["accent"],
                        font=ImageFont.truetype(_FONT_BOLD, 14), anchor="mm")
        
        # List personalities
        y_pos = 50
        for i, name in enumerate(personalities):
            prefix = "▶ " if i == selected else "  "
            color = theme["accent"] if i == selected else theme["fg"]
            self._draw.text((20, y_pos), f"{prefix}{name.title()}", fill=color,
                          font=ImageFont.truetype(_FONT_REGULAR, 12))
            y_pos += 22
            
        # Instructions
        self._draw.text((WIDTH//2, HEIGHT - 30), "Buttons to scroll, hold to select",
                       fill=theme["secondary"], font=ImageFont.truetype(_FONT_REGULAR, 8), anchor="mm")
        
        self._update()
        
    async def show_setup_step(self, step: int, total: int, title: str, description: str = ""):
        """Show setup wizard step"""
        theme = self._get_theme()
        
        self.clear()
        
        # Header
        self._draw.text((WIDTH//2, 25), "🚀 MiBud Setup", fill=theme["accent"],
                        font=ImageFont.truetype(_FONT_BOLD, 16), anchor="mm")
        
        # Progress
        self._draw.text((WIDTH//2, 50), f"Step {step} of {total}",
                       fill=theme["fg"], font=ImageFont.truetype(_FONT_REGULAR, 10), anchor="mm")
        
        # Progress bar
        bar_width = WIDTH - 40
        progress = (step / total) * bar_width
        self._draw.rectangle([20, 65, 20 + bar_width, 75], fill=theme["secondary"])
        self._draw.rectangle([20, 65, 20 + int(progress), 75], fill=theme["accent"])
        
        # Title
        self._draw.text((WIDTH//2, 110), title, fill=theme["fg"],
                        font=ImageFont.truetype(_FONT_BOLD, 14), anchor="mm")
        
        # Description
        if description:
            # Word wrap description
            words = description.split()
            lines = []
            current = ""
            for word in words:
                if len(current + " " + word) <= 30:
                    current = current + " " + word if current else word
                else:
                    lines.append(current)
                    current = word
            if current:
                lines.append(current)
                
            y_pos = 140
            for line in lines[:4]:
                self._draw.text((15, y_pos), line, fill=theme["fg"],
                              font=ImageFont.truetype(_FONT_REGULAR, 10))
                y_pos += 14
                
        self._update()
        
    async def show_shutdown(self):
        """Show shutdown screen"""
        theme = self._get_theme()
        
        self.clear()
        
        self._draw.text((WIDTH//2, HEIGHT//2), "👋 Goodbye!",
                        fill=theme["fg"], font=ImageFont.truetype(_FONT_BOLD, 24), anchor="mm")
        
        self._update()
        
    def wake(self):
        """Wake from sleep"""
        self.is_sleeping = False
        
    def update_clock(self):
        """Update clock display (called frequently)"""
        if self.current_state == "idle" and not self.is_sleeping:
            # Just update internal frame counter for animations
            self._animation_frame = (self._animation_frame + 1) % 360
            
    def update_battery(self, level: int):
        """Update battery display"""
        # Could refresh battery indicator if needed
        pass
        
    def _update(self):
        """Send frame to display"""
        if self._board and self._image:
            try:
                self._board.lcd_show_image(self._image)
            except Exception as e:
                log.debug(f"Display update: {e}")
                
    def _animate(self):
        """Update animation frame"""
        self._animation_frame = (self._animation_frame + 1) % 360
        
    async def cleanup(self):
        """Cleanup display"""
        log.info("📺 Display cleanup")


import asyncio
