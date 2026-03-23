"""
MiBud Demo Mode
Run MiBud in demo mode without hardware (for testing AI components)
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [MiBud-Demo] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("MiBud-Demo")


class MockDisplay:
    """Mock display for demo mode"""
    
    async def initialize(self):
        log.info("📺 [Mock] Display initialized")
        
    def show_boot_animation(self):
        log.info("📺 [Mock] Boot animation playing...")
        
    def update_clock(self):
        pass
        
    def update_battery(self, level):
        pass
        
    def set_state(self, state):
        log.info(f"📺 [Mock] State: {state}")
        
    def show_shutdown(self):
        log.info("📺 [Mock] Shutting down display")


class MockAudio:
    """Mock audio for demo mode"""
    
    async def initialize(self):
        log.info("🔊 [Mock] Audio initialized")
        
    async def play_audio(self, data):
        log.info(f"🔊 [Mock] Playing {len(data)} bytes of audio")
        
    async def record_chunk(self):
        return b""


async def run_demo():
    """Run demo mode"""
    log.info("🎭 Starting MiBud Demo Mode...")
    log.info("=" * 50)
    
    from core.config import Config
    from ai.router import AIRouter
    from ai.stt import STTManager
    from ai.tts import TTSManager
    from ai.conversation import ConversationManager
    from personalities.presets import get_all_personalities
    
    config = Config()
    config.load()
    
    log.info("📋 Configuration loaded")
    
    display = MockDisplay()
    audio = MockAudio()
    
    await display.initialize()
    display.show_boot_animation()
    
    router = AIRouter(config)
    await router.initialize()
    
    log.info("🧠 AI Router initialized")
    log.info(f"   Providers: {list(router._providers.keys())}")
    
    stt = STTManager(config)
    await stt.initialize()
    
    tts = TTSManager(config, audio)
    await tts.initialize()
    
    conversation = ConversationManager(config, audio, router)
    await conversation.initialize()
    
    personalities = get_all_personalities()
    log.info(f"👤 {len(personalities)} personalities loaded")
    
    print("\n" + "=" * 50)
    print("🎭 MiBud Demo Mode Ready!")
    print("=" * 50)
    print("\nAvailable commands:")
    print("  1-20  - Switch personality by number")
    print("  list  - List all personalities")
    print("  quit  - Exit demo")
    print()
    
    async def demo_chat():
        while True:
            try:
                user_input = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: input("You: ").strip()
                )
                
                if not user_input:
                    continue
                    
                if user_input.lower() == "quit":
                    break
                    
                if user_input.lower() == "list":
                    for i, p in enumerate(personalities[:10], 1):
                        print(f"  {i}. {p.emoji} {p.name}")
                    continue
                    
                if user_input.isdigit():
                    idx = int(user_input) - 1
                    if 0 <= idx < len(personalities):
                        p = personalities[idx]
                        await conversation.change_personality(p.id)
                    continue
                
                response = await conversation.process_text_input(user_input)
                if response:
                    print(f"MiBud: {response[:200]}...")
                    
            except EOFError:
                break
            except Exception as e:
                log.error(f"Demo error: {e}")
                
    await demo_chat()
    
    log.info("👋 Demo complete!")


if __name__ == "__main__":
    print("🎭 MiBud Demo Mode")
    print("Testing AI components without hardware\n")
    asyncio.run(run_demo())
