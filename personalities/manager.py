"""
MiBud - Personality Manager
Handles custom personality creation and management
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import asdict

from personalities.presets import PERSONALITIES, get_personality, Personality

log = logging.getLogger("MiBud")


class PersonalityManager:
    """Manages built-in and custom personalities"""
    
    def __init__(self, config_dir: Path = None):
        self.config_dir = config_dir or Path(__file__).parent.parent / "config"
        self.custom_dir = self.config_dir / "personalities"
        self.custom_dir.mkdir(parents=True, exist_ok=True)
        self._custom_personalities: Dict[str, Personality] = {}
        self._load_custom_personalities()
        
    def _load_custom_personalities(self):
        """Load custom personalities from disk"""
        for file in self.custom_dir.glob("*.json"):
            try:
                with open(file, 'r') as f:
                    data = json.load(f)
                    personality = Personality(**data)
                    self._custom_personalities[personality.id] = personality
                    log.info(f"📝 Loaded custom personality: {personality.name}")
            except Exception as e:
                log.error(f"Failed to load personality {file}: {e}")
                
    def _save_custom_personality(self, personality: Personality):
        """Save custom personality to disk"""
        filepath = self.custom_dir / f"{personality.id}.json"
        with open(filepath, 'w') as f:
            json.dump(asdict(personality), f, indent=2)
        log.info(f"💾 Saved personality: {personality.name}")
        
    def get_personality(self, personality_id: str) -> Personality:
        """Get personality by ID (checks custom first, then presets)"""
        if personality_id in self._custom_personalities:
            return self._custom_personalities[personality_id]
        return get_personality(personality_id)
        
    def get_all_personalities(self) -> List[Dict]:
        """Get all personalities with source info"""
        result = []
        
        for p in PERSONALITIES.values():
            result.append({
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "specialty": p.specialty,
                "emoji": p.emoji,
                "source": "preset"
            })
            
        for p in self._custom_personalities.values():
            result.append({
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "specialty": p.specialty,
                "emoji": p.emoji,
                "source": "custom"
            })
            
        return result
        
    def create_personality(self, data: Dict) -> Personality:
        """Create a new custom personality"""
        personality = Personality(
            id=data.get("id", f"custom_{len(self._custom_personalities)}"),
            name=data.get("name", "Custom"),
            description=data.get("description", "A custom personality"),
            specialty=data.get("specialty", "General"),
            emoji=data.get("emoji", "⭐"),
            voice_speed=data.get("voice_speed", 1.0),
            voice_pitch=data.get("voice_pitch", 1.0),
            voice_style=data.get("voice_style", "neutral"),
            theme=data.get("theme", "custom"),
            system_prompt=data.get("system_prompt", ""),
            capabilities=data.get("capabilities", ["chat", "info"]),
            greeting=data.get("greeting", "Hello!")
        )
        
        self._custom_personalities[personality.id] = personality
        self._save_custom_personality(personality)
        
        return personality
        
    def update_personality(self, personality_id: str, data: Dict) -> Optional[Personality]:
        """Update an existing custom personality"""
        if personality_id not in self._custom_personalities:
            return None
            
        personality = self._custom_personalities[personality_id]
        
        for key in ["name", "description", "specialty", "emoji", "voice_speed",
                    "voice_pitch", "voice_style", "theme", "system_prompt",
                    "capabilities", "greeting"]:
            if key in data:
                setattr(personality, key, data[key])
                
        self._save_custom_personality(personality)
        return personality
        
    def delete_personality(self, personality_id: str) -> bool:
        """Delete a custom personality"""
        if personality_id not in self._custom_personalities:
            return False
            
        filepath = self.custom_dir / f"{personality_id}.json"
        if filepath.exists():
            filepath.unlink()
            
        del self._custom_personalities[personality_id]
        log.info(f"🗑️ Deleted personality: {personality_id}")
        return True
        
    def get_personality_details(self, personality_id: str) -> Optional[Dict]:
        """Get full details of a personality"""
        personality = self.get_personality(personality_id)
        if personality:
            return asdict(personality)
        return None
