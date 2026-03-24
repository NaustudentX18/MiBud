"""
MiBud - Speaker Recognition
Identify who's speaking using voice embeddings
"""

import asyncio
import logging
from typing import Dict, List, Optional, Callable
from pathlib import Path
import numpy as np

log = logging.getLogger("MiBud")


class SpeakerProfile:
    """Voice profile for a speaker"""
    
    def __init__(self, speaker_id: str, name: str, embedding: np.ndarray = None):
        self.speaker_id = speaker_id
        self.name = name
        self.embedding = embedding
        self.embedding_count = 0
        self.created_at = None
        self.last_seen = None
        
    def update_embedding(self, new_embedding: np.ndarray):
        """Update voice embedding with running average"""
        if self.embedding is None:
            self.embedding = new_embedding
        else:
            alpha = 0.1
            self.embedding = alpha * new_embedding + (1 - alpha) * self.embedding
        self.embedding_count += 1
        self.last_seen = asyncio.get_event_loop().time()


class SpeakerRecognition:
    """Speaker recognition using voice embeddings"""
    
    def __init__(self, config=None):
        self.config = config
        self.is_initialized = False
        self.is_enabled = config.get("features.speaker_recognition", False) if config else False
        self._profiles: Dict[str, SpeakerProfile] = {}
        self._embedding_model = None
        self._similarity_threshold = 0.7
        self._profiles_dir = Path(__file__).parent.parent / "config" / "speakers"
        self._profiles_dir.mkdir(parents=True, exist_ok=True)
        
    async def initialize(self):
        """Initialize speaker recognition"""
        log.info("🎙️ Initializing speaker recognition...")
        
        if not self.is_enabled:
            log.info("🎙️ Speaker recognition disabled")
            self.is_initialized = True
            return
            
        await self._load_profiles()
        
        try:
            import torch
            import torchaudio
            from speechbrain.inference.speaker import SpeakerRecognition
            
            model_path = self._profiles_dir / "pretrained_models" / "spkrec-ecapa-voxceleb"
            
            if model_path.exists():
                self._embedding_model = SpeakerRecognition.from_hparams(
                    source=str(model_path),
                    savedir=str(model_path)
                )
                log.info("🎙️ Speaker recognition model loaded")
            else:
                log.warning("🎙️ Speaker model not found - using simplified mode")
                
        except ImportError:
            log.warning("🎙️ torch/speechbrain not available - using simplified mode")
        except Exception as e:
            log.warning(f"🎙️ Model loading failed: {e}")
            
        self.is_initialized = True
        log.info("✅ Speaker recognition ready")
        
    async def _load_profiles(self):
        """Load speaker profiles from disk"""
        import json
        
        for file in self._profiles_dir.glob("*.json"):
            if file.name == "pretrained_models":
                continue
            try:
                with open(file, 'r') as f:
                    data = json.load(f)
                    profile = SpeakerProfile(
                        speaker_id=data["speaker_id"],
                        name=data["name"],
                        embedding=np.array(data["embedding"]) if "embedding" in data else None
                    )
                    profile.embedding_count = data.get("embedding_count", 0)
                    profile.created_at = data.get("created_at")
                    profile.last_seen = data.get("last_seen")
                    self._profiles[profile.speaker_id] = profile
                    log.info(f"🎙️ Loaded profile: {profile.name}")
            except Exception as e:
                log.error(f"Failed to load profile {file}: {e}")
                
    def _save_profile(self, profile: SpeakerProfile):
        """Save speaker profile to disk"""
        import json
        
        filepath = self._profiles_dir / f"{profile.speaker_id}.json"
        data = {
            "speaker_id": profile.speaker_id,
            "name": profile.name,
            "embedding": profile.embedding.tolist() if profile.embedding is not None else None,
            "embedding_count": profile.embedding_count,
            "created_at": profile.created_at,
            "last_seen": profile.last_seen
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
            
    async def enroll_speaker(self, speaker_id: str, name: str, audio_samples: List[bytes]) -> bool:
        """Enroll a new speaker with audio samples"""
        log.info(f"🎙️ Enrolling speaker: {name}")
        
        profile = SpeakerProfile(speaker_id, name)
        embeddings = []
        
        for audio_sample in audio_samples:
            embedding = await self._extract_embedding(audio_sample)
            if embedding is not None:
                embeddings.append(embedding)
                
        if embeddings:
            profile.embedding = np.mean(embeddings, axis=0)
            profile.embedding_count = len(embeddings)
            
        self._profiles[speaker_id] = profile
        self._save_profile(profile)
        
        log.info(f"🎙️ Speaker enrolled: {name}")
        return True
        
    async def _extract_embedding(self, audio_data: bytes) -> Optional[np.ndarray]:
        """Extract voice embedding from audio"""
        if self._embedding_model is not None:
            try:
                import io
                import torch
                import torchaudio
                
                waveform, sample_rate = torchaudio.load(io.BytesIO(audio_data))
                
                with torch.no_grad():
                    embeddings = self._embedding_model.encode_batch(waveform)
                    
                return embeddings.squeeze().numpy()
                
            except Exception as e:
                log.warning(f"Embedding extraction failed: {e}")
                
        return None
        
    async def identify_speaker(self, audio_data: bytes) -> Optional[str]:
        """Identify the speaker from audio"""
        if not self._profiles:
            return None
            
        embedding = await self._extract_embedding(audio_data)
        if embedding is None:
            return None
            
        best_match = None
        best_score = 0
        
        for speaker_id, profile in self._profiles.items():
            if profile.embedding is None:
                continue
                
            score = self._cosine_similarity(embedding, profile.embedding)
            
            if score > self._similarity_threshold and score > best_score:
                best_score = score
                best_match = speaker_id
                
        if best_match:
            log.info(f"🎙️ Speaker identified: {self._profiles[best_match].name} ({best_score:.2f})")
            
        return best_match
        
    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """Calculate cosine similarity between two vectors"""
        dot_product = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        
        if norm_a == 0 or norm_b == 0:
            return 0
            
        return dot_product / (norm_a * norm_b)
        
    def get_speaker_name(self, speaker_id: str) -> Optional[str]:
        """Get name for speaker ID"""
        profile = self._profiles.get(speaker_id)
        return profile.name if profile else None
        
    def get_all_profiles(self) -> List[Dict]:
        """Get all speaker profiles"""
        return [
            {
                "speaker_id": p.speaker_id,
                "name": p.name,
                "embedding_count": p.embedding_count,
                "last_seen": p.last_seen
            }
            for p in self._profiles.values()
        ]
        
    def delete_profile(self, speaker_id: str) -> bool:
        """Delete a speaker profile"""
        if speaker_id in self._profiles:
            del self._profiles[speaker_id]
            
            filepath = self._profiles_dir / f"{speaker_id}.json"
            if filepath.exists():
                filepath.unlink()
                
            log.info(f"🎙️ Deleted speaker profile: {speaker_id}")
            return True
        return False
        
    def set_threshold(self, threshold: float):
        """Set identification threshold (0-1)"""
        self._similarity_threshold = max(0.1, min(1.0, threshold))
