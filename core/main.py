"""
MiBud - Privacy-Focused AI Companion
Entry Point

Wires together:
- Hardware (display, audio, buttons, battery, LED, camera)
- AI (router, wake word, STT/TTS, tools, memory)
- Behaviour (conversation manager, proactive engine, power manager)
- Web dashboard
"""

import asyncio
import logging
import signal
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.config import Config
from core.events import EventBus
from core.state import StateManager

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
        self.camera = None
        self.wake_word = None
        self.conversation = None
        self.web_server = None

        # v2 additions
        self.memory = None
        self.tool_context = None
        self.proactive = None
        self.power_manager = None
        self.timer_manager = None
        self.reminder_manager = None
        self.note_manager = None
        self.home_automation = None

    async def initialize(self):
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
        try:
            from web.wizard import SetupWizard
            wizard = SetupWizard(self.config, self.event_bus)
            await wizard.run()
        except Exception as e:
            log.error(f"Setup wizard failed: {e}")
            log.info("Falling back to normal mode")
            await self._start_normal_mode()

    async def _start_normal_mode(self):
        log.info("🎯 Starting MiBud normal mode...")

        await self._init_hardware()
        await self._init_utilities()
        await self._init_memory()
        await self._init_ai()
        await self._init_conversation()
        await self._init_power()
        await self._init_proactive()
        await self._init_web()

        self._setup_event_listeners()

        self.running = True
        await self._main_loop()

    async def _init_hardware(self):
        from core.health import HealthMonitor

        log.info("🔧 Initializing hardware...")
        health = HealthMonitor()

        try:
            from hardware.display import Display
            self.display = Display()
            await self.display.initialize()
            await self.display.show_boot_animation()
        except Exception as e:
            log.warning(f"📺 Display init failed: {e} — using mock")
            self.display = self._create_mock_display()

        try:
            from hardware.audio import AudioManager
            self.audio = AudioManager()
            await self.audio.initialize()
        except Exception as e:
            log.error(f"🔊 Audio init failed: {e} — MiBud requires audio")
            self.audio = None

        try:
            from hardware.buttons import ButtonManager
            self.buttons = ButtonManager()
            self.buttons.set_callbacks(
                on_short_press=self._on_button_press,
                on_long_press=self._on_button_long,
                on_press=self._on_button_hold,
            )
            await self.buttons.initialize()
        except Exception as e:
            log.warning(f"🔘 Buttons init failed: {e}")

        try:
            from hardware.battery import BatteryManager
            self.battery = BatteryManager()
            await self.battery.initialize()
        except Exception as e:
            log.warning(f"🔋 Battery init failed: {e}")

        try:
            from hardware.led import LEDManager
            self.led = LEDManager()
            await self.led.initialize()
        except Exception as e:
            log.warning(f"💡 LED init failed: {e}")

        try:
            from hardware.camera import CameraManager
            self.camera = CameraManager()
            if hasattr(self.camera, "initialize"):
                init = self.camera.initialize()
                if asyncio.iscoroutine(init):
                    await init
        except Exception as e:
            log.warning(f"📷 Camera init failed: {e}")

        health_results = await health.run_all(
            audio=self.audio, display=self.display, battery=self.battery,
        )
        can_proceed, failed = health.can_proceed()
        if not can_proceed:
            log.error(f"🔴 Critical hardware missing: {failed}. Cannot proceed.")
            raise RuntimeError(f"Required hardware not available: {failed}")

        log.info("✅ Hardware initialized")

    def _create_mock_display(self):
        class MockDisplay:
            async def initialize(self):
                pass
            async def show_boot_animation(self):
                log.info("📺 [Mock] Boot animation")
            def update_clock(self):
                pass
            def update_battery(self, level):
                pass
            def set_state(self, state):
                log.info(f"📺 [Mock] State: {state}")
            def show_shutdown(self):
                log.info("📺 [Mock] Shutdown")
            def set_brightness(self, pct):
                log.info(f"📺 [Mock] Brightness: {pct}")
        return MockDisplay()

    async def _init_utilities(self):
        """Timers, reminders, notes."""
        from utils.utilities import TimerManager, ReminderManager, NoteManager
        self.timer_manager = TimerManager()
        self.reminder_manager = ReminderManager()
        self.note_manager = NoteManager()
        log.info("✅ Utilities (timers/reminders/notes) initialized")

        # Home automation is optional
        if self.config.get("features.enable_home_assistant"):
            try:
                from home.automation import HomeAutomation
                self.home_automation = HomeAutomation(self.config)
                if hasattr(self.home_automation, "initialize"):
                    init = self.home_automation.initialize()
                    if asyncio.iscoroutine(init):
                        await init
                log.info("✅ Home automation initialized")
            except Exception as e:
                log.warning(f"🏠 Home automation init failed: {e}")

    async def _init_memory(self):
        """Long-term memory + RAG."""
        if not self.config.get("features.enable_memory", True):
            log.info("🧠 Memory disabled by config")
            return
        try:
            from ai.memory import HashingEmbedder, MemoryStore, OllamaEmbedder
            embed_kind = self.config.get("memory.embedder", "auto")
            embedder = None
            if embed_kind in ("auto", "ollama"):
                url = self.config.get("ai.ollama_url", "http://localhost:11434")
                model = self.config.get("memory.ollama_embed_model", "nomic-embed-text")
                try:
                    probe = OllamaEmbedder(url=url, model=model)
                    await probe.embed("probe")
                    embedder = probe
                    log.info(f"🧠 Using Ollama embedder ({model}, dim={probe.dim})")
                except Exception as e:
                    if embed_kind == "ollama":
                        log.warning(f"ollama embedder unavailable: {e}")
                    embedder = None
            if embedder is None:
                dim = int(self.config.get("memory.hash_dim", 256))
                embedder = HashingEmbedder(dim=dim)
                log.info(f"🧠 Using HashingEmbedder(dim={dim})")
            db_path = self.config.get("memory.db_path", "data/memory.db")
            self.memory = MemoryStore(path=db_path, embedder=embedder)
            stats = self.memory.stats()
            log.info(f"🧠 Memory ready ({stats['facts']} facts, {stats['sessions']} sessions)")
        except Exception as e:
            log.warning(f"🧠 Memory init failed: {e}")
            self.memory = None

    async def _init_ai(self):
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
        log.info("💬 Initializing conversation manager...")
        try:
            from ai.conversation import ConversationManager
            from ai.tools import ToolContext

            self.tool_context = ToolContext(
                config=self.config,
                battery=self.battery,
                camera=self.camera,
                audio=self.audio,
                display=self.display,
                led=self.led,
                buttons=self.buttons,
                ai_router=self.ai_router,
                memory=self.memory,
                timer_manager=self.timer_manager,
                reminder_manager=self.reminder_manager,
                note_manager=self.note_manager,
                home_automation=self.home_automation,
            )

            self.conversation = ConversationManager(
                self.config,
                self.audio,
                self.ai_router,
                memory=self.memory,
                tool_context=self.tool_context,
            )
            # Tool context also needs the conversation (for set_personality).
            self.tool_context.conversation = self.conversation
            await self.conversation.initialize()

            self.conversation.register_callback("state_changed", self._on_conversation_state)
            log.info("✅ Conversation manager initialized")
        except Exception as e:
            log.error(f"Conversation init failed: {e}")

    async def _init_power(self):
        """Power profile manager."""
        if not self.config.get("features.enable_power_manager", True):
            log.info("⚡ Power manager disabled by config")
            return
        try:
            from core.power import PowerManager, PowerManagerConfig, PowerProfile

            cfg = PowerManagerConfig(
                auto=bool(self.config.get("power.auto", True)),
                eco_below_percent=int(self.config.get("power.eco_below_percent", 25)),
                performance_on_charge=bool(self.config.get("power.performance_on_charge", True)),
                manual_profile=PowerProfile(self.config.get("power.manual_profile", "balanced")),
            )
            self.power_manager = PowerManager(cfg, battery=self.battery)
            self.power_manager.subscribe(self._on_power_profile)
            await self.power_manager.start()
        except Exception as e:
            log.warning(f"⚡ Power manager init failed: {e}")

    async def _init_proactive(self):
        """Proactive engine (idle speaking / alerts)."""
        if not self.config.get("features.enable_proactive", True):
            log.info("🟢 Proactive engine disabled by config")
            return
        try:
            from core.proactive import ProactiveConfig, ProactiveEngine

            cfg = ProactiveConfig(
                enabled=True,
                battery_enabled=bool(self.config.get("proactive.battery_enabled", True)),
                low_battery_percent=int(self.config.get("tuning.battery_low_threshold", 20)),
                critical_battery_percent=int(self.config.get("tuning.battery_critical_threshold", 5)),
                reminders_enabled=bool(self.config.get("proactive.reminders_enabled", True)),
                timers_enabled=bool(self.config.get("proactive.timers_enabled", True)),
                idle_checkin_enabled=bool(self.config.get("proactive.idle_checkin_enabled", False)),
                idle_checkin_minutes=int(self.config.get("proactive.idle_checkin_minutes", 30)),
                anomaly_enabled=bool(self.config.get("proactive.anomaly_enabled", True)),
                morning_greeting_enabled=bool(self.config.get("proactive.morning_greeting_enabled", False)),
                morning_greeting_hour=int(self.config.get("proactive.morning_greeting_hour", 7)),
                quiet_hours_start=int(self.config.get("proactive.quiet_hours_start", 23)),
                quiet_hours_end=int(self.config.get("proactive.quiet_hours_end", 7)),
            )

            async def _speak(text: str):
                if self.conversation is None:
                    return
                await self.conversation.tts.speak(text)

            def _is_busy() -> bool:
                if self.conversation is not None and self.conversation.is_busy():
                    return True
                return self.state.get_state() in ("listening", "processing", "speaking")

            self.proactive = ProactiveEngine(
                cfg,
                battery=self.battery,
                reminder_manager=self.reminder_manager,
                timer_manager=self.timer_manager,
                speak=_speak,
                is_busy=_is_busy,
            )
            await self.proactive.start()
        except Exception as e:
            log.warning(f"🟢 Proactive engine init failed: {e}")

    def _on_power_profile(self, settings):
        """Apply power profile changes to display + wake-word."""
        log.info(f"⚡ applying power profile '{settings.name.value}'")
        try:
            if self.display is not None and hasattr(self.display, "set_brightness"):
                self.display.set_brightness(settings.display_brightness)
        except Exception as e:
            log.debug(f"brightness apply skipped: {e}")
        try:
            if self.wake_word is not None and hasattr(self.wake_word, "set_poll_interval"):
                self.wake_word.set_poll_interval(settings.wake_poll_ms / 1000.0)
        except Exception as e:
            log.debug(f"wake-word poll apply skipped: {e}")

    def _setup_event_listeners(self):
        @self.event_bus.on("button_press")
        async def handle_button_press(data):
            button = data.get("button") if isinstance(data, dict) else None
            log.info(f"🔘 Button pressed: {button}")
            if button == "A":
                await self._activate_listening()
            elif button == "B":
                await self._cycle_personality()

        @self.event_bus.on("wake_word_detected")
        async def handle_wake_word(data):
            word = data.get("word") if isinstance(data, dict) else None
            log.info(f"🔔 Wake word: {word}")
            await self._activate_listening()

        @self.event_bus.on("state_changed")
        async def handle_state_change(data):
            if self.display:
                state = data.get("state", "idle") if isinstance(data, dict) else "idle"
                self.display.set_state(state)

    async def _on_wake_word(self, wake_word: str):
        log.info(f"🔔 Wake word triggered: {wake_word}")
        await self.event_bus.emit("wake_word_detected", {"word": wake_word})
        await self._activate_listening()

    async def _on_conversation_state(self, state: str):
        if self.display:
            self.display.set_state(state)
        if self.led:
            await self._update_led_for_state(state)

    async def _update_led_for_state(self, state: str):
        colors = {
            "idle": "green",
            "listening": "blue",
            "thinking": "yellow",
            "speaking": "purple",
            "error": "red",
        }
        try:
            await self.led.set_color(colors.get(state, "green"))
        except Exception:
            pass

    async def _activate_listening(self):
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
        if not self.conversation:
            return
        from personalities.presets import PERSONALITIES
        personalities = list(PERSONALITIES.keys())
        current = self.config.get("personality.current", "assistant")
        if current in personalities:
            idx = personalities.index(current)
            next_id = personalities[(idx + 1) % len(personalities)]
            await self.conversation.change_personality(next_id)

    async def _init_web(self):
        log.info("🌐 Starting web interface...")
        try:
            from web.api_v2 import bind_services
            from web.server import run_server

            bind_services(
                memory=self.memory,
                conversation=self.conversation,
                ai_router=self.ai_router,
                power_manager=self.power_manager,
                tool_registry=(self.ai_router._tools if self.ai_router else None),
            )
            self._web_task = asyncio.create_task(asyncio.to_thread(run_server))
            log.info("✅ Web interface ready at http://mibud.local:5000")
        except Exception as e:
            log.warning(f"Web init warning: {e}")

    async def _main_loop(self):
        log.info("🔄 MiBud running - Press Ctrl+C to stop")
        counter = 0
        while self.running:
            try:
                counter += 1
                if self.battery is not None:
                    level = self.battery.get_level()
                    if self.display and counter % 10 == 0:
                        self.display.update_battery(level)
                if self.wake_word is not None and not getattr(self.wake_word, "is_listening", False):
                    await self.wake_word.start()
                if self.display:
                    try:
                        self.display.update_clock()
                    except Exception:
                        pass
                await self.event_bus.process_events()
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"Main loop error: {e}")

    def _on_button_press(self, button_id: str):
        log.info(f"🔘 Button pressed: {button_id}")
        self.event_bus.dispatch("button_press", {"button": button_id})

    def _on_button_long(self, button_id: str):
        log.info(f"🔘 Button long press: {button_id}")
        self.event_bus.dispatch("button_long_press", {"button": button_id})

    def _on_button_hold(self, button_id: str):
        log.info(f"🔘 Button hold: {button_id}")

    async def shutdown(self):
        if not self.running:
            return
        log.info("🛑 Shutting down MiBud...")
        self.running = False
        try:
            if self.proactive is not None:
                await self.proactive.stop()
            if self.power_manager is not None:
                await self.power_manager.stop()
            if self.wake_word is not None:
                await self.wake_word.stop()
            if self.conversation is not None:
                await self.conversation.stop()
            if self.memory is not None:
                self.memory.close()
            if self.display is not None:
                try:
                    self.display.show_shutdown()
                except Exception:
                    pass
            if hasattr(self, "_web_task") and self._web_task:
                self._web_task.cancel()
        except Exception as e:
            log.error(f"Shutdown error: {e}")

        log.info("👋 MiBud stopped")


async def main():
    app = MiBudApp()
    import threading
    shutdown_event = threading.Event()

    def signal_handler(sig, frame):
        log.info(f"Received signal {sig.name} — initiating shutdown")
        shutdown_event.set()

    old_handlers = {
        signal.SIGINT: signal.signal(signal.SIGINT, signal_handler),
        signal.SIGTERM: signal.signal(signal.SIGTERM, signal_handler),
    }

    try:
        await app.initialize()
        while not shutdown_event.is_set():
            await asyncio.sleep(0.5)
        await app.shutdown()
    except Exception as e:
        log.error(f"Fatal error: {e}")
        sys.exit(1)
    finally:
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    asyncio.run(main())
