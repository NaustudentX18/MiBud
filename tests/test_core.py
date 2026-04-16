"""
MiBud Tests
Basic tests for core functionality
"""

import unittest
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestConfig(unittest.TestCase):
    """Test configuration"""
    
    def test_config_creation(self):
        from core.config import Config
        config = Config()
        self.assertIsNotNone(config.data)
        self.assertIn("ai", config.data)
        self.assertIn("personality", config.data)
        
    def test_config_get_set(self):
        from core.config import Config
        config = Config()
        config.set("test.value", "hello")
        self.assertEqual(config.get("test.value"), "hello")
        
    def test_api_key_check(self):
        import os
        from core.config import Config
        # API keys must come from env vars, not from disk
        os.environ["OPENAI_API_KEY"] = "sk-test"
        config = Config()
        self.assertTrue(config.has_api_key("openai"))
        self.assertFalse(config.has_api_key("anthropic"))


class TestState(unittest.TestCase):
    """Test state machine"""
    
    def test_state_creation(self):
        from core.state import StateManager
        state = StateManager()
        self.assertEqual(state.get_state(), "idle")
        
    def test_state_change(self):
        from core.state import StateManager
        state = StateManager()
        state.set_state("listening")
        self.assertEqual(state.get_state(), "listening")


class TestPersonalities(unittest.TestCase):
    """Test personality system"""
    
    def test_get_personality(self):
        from personalities.presets import get_personality
        p = get_personality("assistant")
        self.assertEqual(p.id, "assistant")
        self.assertEqual(p.name, "Assistant")
        
    def test_all_personalities(self):
        from personalities.presets import get_all_personalities
        personalities = get_all_personalities()
        self.assertGreater(len(personalities), 15)
        
    def test_custom_personality(self):
        from personalities.presets import get_personality
        p = get_personality("chef")
        self.assertEqual(p.specialty, "Cooking and recipes")


class TestAIRouter(unittest.TestCase):
    """Test AI router"""
    
    def test_router_creation(self):
        from core.config import Config
        from ai.router import AIRouter
        config = Config()
        router = AIRouter(config)
        self.assertIsNotNone(router)
        
    def test_provider_enum(self):
        from ai.router import AIProvider
        self.assertEqual(AIProvider.OLLAMA.value, "ollama")
        self.assertEqual(AIProvider.OPENAI.value, "openai")


class TestPersonalityManager(unittest.TestCase):
    """Test personality manager"""
    
    def test_manager_creation(self):
        from personalities.manager import PersonalityManager
        manager = PersonalityManager()
        self.assertIsNotNone(manager)
        
    def test_get_all_personalities(self):
        from personalities.manager import PersonalityManager
        manager = PersonalityManager()
        all_p = manager.get_all_personalities()
        self.assertIsInstance(all_p, list)
        self.assertGreaterEqual(len(all_p), 20)


if __name__ == "__main__":
    unittest.main()
