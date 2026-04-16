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
        
        self.display = None
        self.audio = None
        self.buttons = None
        self.battery = None
        self.led = None
        self.wake_word = None
        self.conversation = None
        self.web_server = None
        
    async def initialize(self):
        """Initialize all components"""
        log.info("🚀 Initializing MiBud...")
        
        self.config.load()
        self.config.print_summary()
        
        await self.state.initialize()
        
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
        
        await self._init_hardware()
        await self._init_ai()
        await self._init_conversation()
        await self._init_web()
        
        self._setup_event_listeners()
        
        self.running = True
        await self._main_loop()
        
    async def _init_hardware(self):
        """Initialize hardware components with per-subsystem fallbacks"""
        from core.health import HealthMonitor

        log.info("🔧 Initializing hardware...")
        health = HealthMonitor()

        # Display — optional
        try:
            from hardware.display import Display
            self.display = Display()
            await self.display.initialize()
            await self.display.show_boot_animation()
        except Exception as e:
            log.warning(f"📺 Display init failed: {e} — using mock")
            self.display = self._create_mock_display()

        # Audio — required
        try:
            from hardware.audio import AudioManager
            self.audio = AudioManager()
            await self.audio.initialize()
        except Exception as e:
            log.error(f"🔊 Audio init failed: {e} — MiBud requires audio")
            self.audio = None

        # Buttons — optional
        try:
            from hardware.buttons import ButtonManager
            self.buttons = ButtonManager()
            self.buttons.set_callbacks(
                on_short_press=self._on_button_press,
                on_long_press=self._on_button_long,
                on_press=self._on_button_hold
            )
            await self.buttons.initialize()
        except Exception as e:
            log.warning(f"🔘 Buttons init failed: {e}")

        # Battery — optional
        try:
            from hardware.battery import BatteryManager
            self.battery = BatteryManager()
            await self.battery.initialize()
        except Exception as e:
            log.warning(f"🔋 Battery init failed: {e}")

        # LED — optional
        try:
            from hardware.led import LEDManager
            self.led = LEDManager()
            await self.led.initialize()
        except Exception as e:
            log.warning(f"💡 LED init failed: {e}")

        # Run health checks
        health_results = await health.run_all(
            audio=self.audio,
            display=self.display,
            battery=self.battery
        )
        can_proceed, failed = health.can_proceed()
        if not can_proceed:
            log.error(f"🔴 Critical hardware missing: {failed}. Cannot proceed.")
            raise RuntimeError(f"Required hardware not available: {failed}")

        log.info("✅ Hardware initialized")
            
    def _create_mock_display(self):
        """Create a mock display for non-RPi platforms"""
        class MockDisplay:
            async def initialize(self): pass
            def show_boot_animation(self): log.info("📺 [Mock] Boot animation")
            def update_clock(self): pass
            def update_battery(self, level): pass
            def set_state(self, state): log.info(f"📺 [Mock] State: {state}")
            def show_shutdown(self): log.info("📺 [Mock] Shutdown")
        return MockDisplay()
            
    async def _init_ai(self):
        """Initialize AI system"""
        log.info("🧠 Initializing AI system...")
        
        try:
            from ai.router import AIRouter
            from ai.wakeword import WakeWordDetector
            
            self.ai_router = AIRouter(self.config)
            await self.ai_router.initialize()
            
            self.wake_word = WakeWordDetector(self.config, self.audio)
            self.wake_word.set_callback(self._on_wake_word)
            await self.wake_word.initialize()
            
            log.info("✅ AI system initialized")
            
        except Exception as e:
            log.error(f"AI init failed: {e}")
            self.ai_router = None
            self.wake_word = None
            
    async def _init_conversation(self):
        """Initialize conversation manager"""
        log.info("💬 Initializing conversation manager...")
        
        try:
            from ai.conversation import ConversationManager
            
            self.conversation = ConversationManager(
                self.config, 
                self.audio,
                self.ai_router
            )
            await self.conversation.initialize()
            
            self.conversation.register_callback("state_changed", self._on_conversation_state)
            
            log.info("✅ Conversation manager initialized")
            
        except Exception as e:
            log.error(f"Conversation init failed: {e}")
            
    def _setup_event_listeners(self):
        """Setup event bus listeners"""
        @self.event_bus.on("button_press")
        async def handle_button_press(data):
            button = data.get("button")
            log.info(f"🔘 Button pressed: {button}")
            
            if button == "A":
                await self._activate_listening()
            elif button == "B":
                await self._cycle_personality()
                
        @self.event_bus.on("wake_word_detected")
        async def handle_wake_word(data):
            word = data.get("word")
            log.info(f"🔔 Wake word: {word}")
            await self._activate_listening()
            
        @self.event_bus.on("state_changed")
        async def handle_state_change(data):
            if self.display:
                self.display.set_state(data.get("state", "idle"))
                
    async def _on_wake_word(self, wake_word: str):
        """Handle wake word detection"""
        log.info(f"🔔 Wake word triggered: {wake_word}")
        self.event_bus.emit("wake_word_detected", {"word": wake_word})
        await self._activate_listening()
        
    async def _on_conversation_state(self, state: str):
        """Handle conversation state changes"""
        if self.display:
            self.display.set_state(state)
        if self.led:
            await self._update_led_for_state(state)
            
    async def _update_led_for_state(self, state: str):
        """Update LED based on state"""
        colors = {
            "idle": "green",
            "listening": "blue",
            "thinking": "yellow",
            "speaking": "purple",
            "error": "red"
        }
        await self.led.set_color(colors.get(state, "green"))
        
    async def _activate_listening(self):
        """Activate listening mode"""
        if self.state.get_state() == "listening":
            return
            
        self.state.set_state("listening")
        
        if self.wake_word:
            await self.wake_word.stop()
            
        if self.conversation:
            await self.conversation.listen_for_command()
            
        if self.wake_word:
            await self.wake_word.start()
            
        self.state.set_state("idle")
        
    async def _cycle_personality(self):
        """Cycle to next personality"""
        if not self.conversation:
            return
            
        from personalities.presets import PERSONALITIES
        personalities = list(PERSONALITIES.keys())
        current = self.config.get("personality.current", "assistant")
        
        if current in personalities:
            idx = personalities.index(current)
            next_idx = (idx + 1) % len(personalities)
            next_id = personalities[next_idx]
            
            await self.conversation.change_personality(next_id)
            
    async def _init_web(self):
        """Initialize web interface"""
        log.info("🌐 Starting web interface...")
        
        try:
            from web.server import run_server
            
            self._web_task = asyncio.create_task(
                asyncio.to_thread(run_server)
            )
            
            log.info("✅ Web interface ready at http://mibud.local:5000")
            
        except Exception as e:
            log.warning(f"Web init warning: {e}")
            
    async def _main_loop(self):
        """Main event loop"""
        log.info("🔄 MiBud running - Press Ctrl+C to stop")
        
        counter = 0
        while self.running:
            try:
                counter += 1
                
                if hasattr(self, 'battery') and self.battery:
                    level = self.battery.get_level()
                    if self.display and counter % 10 == 0:
                        self.display.update_battery(level)
                        
                if hasattr(self, 'wake_word') and self.wake_word:
                    if not self.wake_word.is_listening:
                        await self.wake_word.start()
                        
                if self.display:
                    self.display.update_clock()
                    
                await self.event_bus.process_events()
                await asyncio.sleep(1)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Main loop error: {e}")
                
    def _on_button_press(self, button_id: str):
        """Handle button press"""
        log.info(f"🔘 Button pressed: {button_id}")
        self.event_bus.emit("button_press", {"button": button_id})
        
    def _on_button_long(self, button_id: str):
        """Handle button long press"""
        log.info(f"🔘 Button long press: {button_id}")
        self.event_bus.emit("button_long_press", {"button": button_id})
        
    def _on_button_hold(self, button_id: str):
        """Handle button hold"""
        log.info(f"🔘 Button hold: {button_id}")
        
    async def shutdown(self):
        """Graceful shutdown — idempotent"""
        if not self.running:
            return  # Already shutting down
        log.info("🛑 Shutting down MiBud...")
        self.running = False

        try:
            if hasattr(self, 'wake_word') and self.wake_word:
                await self.wake_word.stop()
            if hasattr(self, 'conversation') and self.conversation:
                await self.conversation.stop()
            if hasattr(self, 'display') and self.display:
                self.display.show_shutdown()
            if hasattr(self, '_web_task') and self._web_task:
                self._web_task.cancel()
        except Exception as e:
            log.error(f"Shutdown error: {e}")

        log.info("👋 MiBud stopped")


async def main():
    """Main entry point"""
    app = MiBudApp()

    # Thread-safe shutdown flag
    import threading
    shutdown_event = threading.Event()

    def signal_handler(sig, frame):
        """Sync signal handler — sets an event that the loop checks"""
        log.info(f"Received signal {sig.name} — initiating shutdown")
        shutdown_event.set()

    old_handlers = {
        signal.SIGINT: signal.signal(signal.SIGINT, signal_handler),
        signal.SIGTERM: signal.signal(signal.SIGTERM, signal_handler),
    }

    try:
        await app.initialize()
        # Main loop checks shutdown_event instead of app.running
        while not shutdown_event.is_set():
            await asyncio.sleep(0.5)
        await app.shutdown()
    except Exception as e:
        log.error(f"Fatal error: {e}")
        sys.exit(1)
    finally:
        # Restore original handlers
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    asyncio.run(main())
