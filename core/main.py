"""
MiBud - Privacy-Focused AI Companion
Entry Point

A versatile, privacy-focused AI assistant combining:
- Working base from pizero-openclaw
- Advanced AI routing from Omni-Bot
- 20+ personalities
- Offline + Online modes
"""

import os
import sys
import logging
import signal
import asyncio
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.config import Config
from core.state import StateManager
from core.events import EventBus

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MiBud] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/tmp/mibud.log", mode="a"),
    ],
)
log = logging.getLogger("MiBud")


class MiBudApp:
    """Main MiBud Application"""
    
    def __init__(self):
        self.config = Config()
        self.state = StateManager()
        self.event_bus = EventBus()
        self.running = False
        self.workers = []
        
    async def initialize(self):
        """Initialize all components"""
        log.info("🚀 Initializing MiBud...")
        
        # Load configuration
        self.config.load()
        self.config.print_summary()
        
        # Initialize state
        await self.state.initialize()
        
        # Check if first run (setup wizard needed)
        if self.config.is_first_run():
            log.info("📝 First run detected - starting setup wizard")
            await self._run_setup_wizard()
        else:
            log.info("✅ Configuration loaded - starting normal mode")
            await self._start_normal_mode()
            
    async def _run_setup_wizard(self):
        """Launch setup wizard"""
        try:
            from web.wizard import SetupWizard
            wizard = SetupWizard(self.config, self.event_bus)
            await wizard.run()
        except Exception as e:
            log.error(f"Setup wizard failed: {e}")
            log.info("Falling back to normal mode")
            await self._start_normal_mode()
            
    async def _start_normal_mode(self):
        """Start normal operation mode"""
        log.info("🎯 Starting MiBud normal mode...")
        
        # Initialize hardware
        await self._init_hardware()
        
        # Initialize AI
        await self._init_ai()
        
        # Start web interface
        await self._init_web()
        
        # Start main event loop
        self.running = True
        await self._main_loop()
        
    async def _init_hardware(self):
        """Initialize hardware components"""
        try:
            from hardware.display import Display
            from hardware.audio import AudioManager
            from hardware.buttons import ButtonManager
            from hardware.battery import BatteryManager
            from hardware.led import LEDManager
            
            log.info("🔧 Initializing hardware...")
            
            # Display
            self.display = Display()
            await self.display.initialize()
            self.display.show_boot_animation()
            
            # Audio
            self.audio = AudioManager()
            await self.audio.initialize()
            
            # Buttons
            self.buttons = ButtonManager()
            self.buttons.set_callbacks(
                on_short_press=self._on_button_press,
                on_long_press=self._on_button_long,
                on_press=self._on_button_hold
            )
            await self.buttons.initialize()
            
            # Battery
            self.battery = BatteryManager()
            await self.battery.initialize()
            
            # LED
            self.led = LEDManager()
            await self.led.initialize()
            
            log.info("✅ Hardware initialized")
            
        except Exception as e:
            log.warning(f"Hardware init warning: {e}")
            
    async def _init_ai(self):
        """Initialize AI system"""
        try:
            from ai.router import AIRouter
            
            log.info("🧠 Initializing AI system...")
            
            self.ai_router = AIRouter(self.config)
            await self.ai_router.initialize()
            
            log.info("✅ AI system initialized")
            
        except Exception as e:
            log.error(f"AI init failed: {e}")
            
    async def _init_web(self):
        """Initialize web interface"""
        try:
            from web.server import WebServer
            
            log.info("🌐 Starting web interface...")
            
            self.web_server = WebServer(self.config, self.state)
            await self.web_server.start()
            
            log.info("✅ Web interface ready at http://mibud.local:5000")
            
        except Exception as e:
            log.warning(f"Web init warning: {e}")
            
    async def _main_loop(self):
        """Main event loop"""
        log.info("🔄 MiBud running - Press Ctrl+C to stop")
        
        while self.running:
            try:
                # Update battery display
                if hasattr(self, 'battery'):
                    battery_level = self.battery.get_level()
                    self.display.update_battery(battery_level)
                    
                # Update clock
                self.display.update_clock()
                
                # Check for events
                await self.event_bus.process_events()
                
                # Sleep
                await asyncio.sleep(1)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Main loop error: {e}")
                
    def _on_button_press(self, button_id: str):
        """Handle button press"""
        log.info(f"🔘 Button pressed: {button_id}")
        self.event_bus.dispatch("button_press", {"button": button_id})
        
    def _on_button_long(self, button_id: str):
        """Handle button long press"""
        log.info(f"🔘 Button long press: {button_id}")
        self.event_bus.dispatch("button_long_press", {"button": button_id})
        
    def _on_button_hold(self, button_id: str):
        """Handle button hold"""
        log.info(f"🔘 Button hold: {button_id}")
        
    async def shutdown(self):
        """Graceful shutdown"""
        log.info("🛑 Shutting down MiBud...")
        self.running = False
        
        try:
            if hasattr(self, 'display'):
                self.display.show_shutdown()
            if hasattr(self, 'web_server'):
                await self.web_server.stop()
        except Exception as e:
            log.error(f"Shutdown error: {e}")
            
        log.info("👋 MiBud stopped")


async def main():
    """Main entry point"""
    app = MiBudApp()
    
    # Setup signal handlers
    def signal_handler(sig, frame):
        log.info("Received interrupt signal")
        asyncio.create_task(app.shutdown())
        
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await app.initialize()
    except Exception as e:
        log.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
