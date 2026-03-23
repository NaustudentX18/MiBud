"""
MiBud - Configuration Management
Handles all configuration including AI providers, personalities, and settings
"""

import os
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Config:
    """MiBud Configuration Manager"""
    
    def __init__(self):
        self.config_dir = Path(__file__).parent.parent / "config"
        self.config_file = self.config_dir / "config.json"
        self.profiles_dir = self.config_dir / "profiles"
        
        # Default configuration
        self.data: Dict[str, Any] = {
            # AI Configuration
            "ai": {
                "default_provider": "openrouter",  # openai, anthropic, google, deepseek, ollama, openrouter
                "offline_provider": "ollama",
                "stt_provider": "whisper_api",  # whisper_api, faster_whisper, vosk
                "tts_provider": "openai_tts",  # openai_tts, piper, coqui, pyttsx3
                "model": "google/gemini-2.0-flash-lite:free",
                "offline_model": "phi-3.5-mini-instruct-q4_k_m.gguf",
                "ollama_url": "http://localhost:11434",
            },
            # API Keys
            "api_keys": {
                "openai": os.getenv("OPENAI_API_KEY", ""),
                "anthropic": os.getenv("ANTHROPIC_API_KEY", ""),
                "google": os.getenv("GOOGLE_API_KEY", ""),
                "deepseek": os.getenv("DEEPSEEK_API_KEY", ""),
                "openrouter": os.getenv("OPENROUTER_API_KEY", ""),
                "elevenlabs": os.getenv("ELEVENLABS_API_KEY", ""),
            },
            # Personality
            "personality": {
                "current": "assistant",
                "voice_speed": 1.0,
                "voice_pitch": 1.0,
                "voice_style": "neutral",
            },
            # Wake Word
            "wake_word": {
                "enabled": True,
                "words": ["hey mibud", "ok pi", "hey assistant"],
                "sensitivity": 0.5,
                "use_button": True,
            },
            # Hardware
            "hardware": {
                "display_brightness": 70,
                "display_rotation": 0,
                "audio_input_device": "plughw:1,0",
                "audio_output_device": "default",
                "audio_sample_rate": 16000,
                "enable_led": True,
            },
            # Display
            "display": {
                "theme": "auto",  # auto, dark, light
                "show_clock": True,
                "show_battery": True,
                "show_wifi": True,
                "idle_timeout": 60,
                "sleep_timeout": 300,
            },
            # Network
            "network": {
                "hostname": "mibud",
                "auto_reconnect": True,
            },
            # Features
            "features": {
                "enable_tts": True,
                "enable_stt": True,
                "enable_weather": True,
                "enable_timers": True,
                "enable_home_assistant": False,
            },
            # First run tracking
            "first_run": True,
            "setup_complete": False,
        }
        
    def load(self):
        """Load configuration from file"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    saved = json.load(f)
                    self.data.update(saved)
            except Exception as e:
                print(f"Warning: Could not load config: {e}")
                
    def save(self):
        """Save configuration to file"""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, 'w') as f:
            json.dump(self.data, f, indent=2)
            
    def is_first_run(self) -> bool:
        """Check if this is first run"""
        return self.data.get("first_run", True) or not self.data.get("setup_complete", False)
    
    def mark_setup_complete(self):
        """Mark setup as complete"""
        self.data["first_run"] = False
        self.data["setup_complete"] = True
        self.save()
        
    def get(self, key: str, default: Any = None) -> Any:
        """Get config value using dot notation"""
        keys = key.split(".")
        value = self.data
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
        return value if value is not None else default
    
    def set(self, key: str, value: Any):
        """Set config value using dot notation"""
        keys = key.split(".")
        data = self.data
        for k in keys[:-1]:
            if k not in data:
                data[k] = {}
            data = data[k]
        data[keys[-1]] = value
        
    def get_api_key(self, provider: str) -> str:
        """Get API key for provider"""
        return self.data.get("api_keys", {}).get(provider, "")
    
    def has_api_key(self, provider: str) -> bool:
        """Check if API key exists for provider"""
        key = self.get_api_key(provider)
        return bool(key and key.strip())
    
    def get_all_providers(self) -> List[str]:
        """Get list of configured providers"""
        providers = []
        if self.has_api_key("openai"):
            providers.append("openai")
        if self.has_api_key("anthropic"):
            providers.append("anthropic")
        if self.has_api_key("google"):
            providers.append("google")
        if self.has_api_key("deepseek"):
            providers.append("deepseek")
        if self.has_api_key("openrouter"):
            providers.append("openrouter")
        return providers
        
    def print_summary(self):
        """Print configuration summary"""
        print("\n" + "="*50)
        print("MiBud Configuration Summary")
        print("="*50)
        
        # AI Providers
        print(f"\n🧠 AI Configuration:")
        print(f"   Default Provider: {self.get('ai.default_provider')}")
        print(f"   Model: {self.get('ai.model')}")
        print(f"   Offline Model: {self.get('ai.offline_model')}")
        
        # Providers
        providers = self.get_all_providers()
        print(f"   Configured Providers: {', '.join(providers) if providers else 'None'}")
        
        # Personality
        print(f"\n👤 Personality: {self.get('personality.current')}")
        
        # Wake Word
        ww_enabled = self.get('wake_word.enabled')
        ww_words = self.get('wake_word.words')
        print(f"\n🎤 Wake Word:")
        print(f"   Enabled: {ww_enabled}")
        print(f"   Words: {', '.join(ww_words)}")
        
        # Hardware
        print(f"\n🔧 Hardware:")
        print(f"   Display Brightness: {self.get('hardware.display_brightness')}%")
        print(f"   Audio Input: {self.get('hardware.audio_input_device')}")
        
        # Features
        print(f"\n⚡ Features:")
        print(f"   TTS: {self.get('features.enable_tts')}")
        print(f"   STT: {self.get('features.enable_stt')}")
        print(f"   Weather: {self.get('features.enable_weather')}")
        
        print("\n" + "="*50 + "\n")


# Global config instance
_config: Optional[Config] = None

def get_config() -> Config:
    """Get global config instance"""
    global _config
    if _config is None:
        _config = Config()
        _config.load()
    return _config
