"""
MiBud AI - Router
Multi-Provider AI Routing with Offline Fallback
"""

import os
import logging
import asyncio
import time
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
from enum import Enum

log = logging.getLogger("MiBud")


class AIProvider(Enum):
    """Supported AI providers"""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    DEEPSEEK = "deepseek"
    OLLAMA = "ollama"
    OPENROUTER = "openrouter"


@dataclass
class AIResponse:
    """Standardized AI response"""
    text: str
    provider: str
    model: str
    latency_ms: int
    confidence: float = 1.0
    error: Optional[str] = None


@dataclass  
class ChatMessage:
    """Chat message"""
    role: str  # system, user, assistant
    content: str


class AIRouter:
    """Routes AI requests to appropriate provider with fallback"""
    
    def __init__(self, config):
        self.config = config
        self.is_initialized = False
        self._providers: Dict[str, Any] = {}
        self._current_provider = None
        self._offline_provider = AIProvider.OLLAMA
        self._online_provider = AIProvider.OPENROUTER
        
    async def initialize(self):
        """Initialize AI providers"""
        log.info("🧠 Initializing AI router...")
        
        # Initialize each provider
        if self.config.has_api_key("openai"):
            await self._init_openai()
        if self.config.has_api_key("anthropic"):
            await self._init_anthropic()
        if self.config.has_api_key("google"):
            await self._init_google()
        if self.config.has_api_key("deepseek"):
            await self._init_deepseek()
        if self.config.has_api_key("openrouter"):
            await self._init_openrouter()
            
        # Always init Ollama for offline
        await self._init_ollama()
        
        # Set default provider
        default = self.config.get("ai.default_provider", "openrouter")
        self._current_provider = default
        
        self.is_initialized = True
        log.info(f"✅ AI router initialized with {len(self._providers)} providers")
        
    async def _init_openai(self):
        """Initialize OpenAI provider"""
        try:
            from openai import OpenAI
            api_key = self.config.get_api_key("openai")
            if api_key:
                self._providers["openai"] = {
                    "client": OpenAI(api_key=api_key),
                    "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"]
                }
                log.info("✅ OpenAI provider ready")
        except Exception as e:
            log.warning(f"OpenAI init failed: {e}")
            
    async def _init_anthropic(self):
        """Initialize Anthropic provider"""
        try:
            from anthropic import Anthropic
            api_key = self.config.get_api_key("anthropic")
            if api_key:
                self._providers["anthropic"] = {
                    "client": Anthropic(api_key=api_key),
                    "models": ["claude-3-5-sonnet-latest", "claude-3-haiku-latest"]
                }
                log.info("✅ Anthropic provider ready")
        except Exception as e:
            log.warning(f"Anthropic init failed: {e}")
            
    async def _init_google(self):
        """Initialize Google provider"""
        try:
            import google.generativeai as genai
            api_key = self.config.get_api_key("google")
            if api_key:
                genai.configure(api_key=api_key)
                self._providers["google"] = {
                    "client": genai,
                    "models": ["gemini-2.0-flash", "gemini-pro"]
                }
                log.info("✅ Google provider ready")
        except Exception as e:
            log.warning(f"Google init failed: {e}")
            
    async def _init_deepseek(self):
        """Initialize DeepSeek provider"""
        try:
            from openai import OpenAI
            api_key = self.config.get_api_key("deepseek")
            if api_key:
                self._providers["deepseek"] = {
                    "client": OpenAI(api_key=api_key, base_url="https://api.deepseek.com"),
                    "models": ["deepseek-chat"]
                }
                log.info("✅ DeepSeek provider ready")
        except Exception as e:
            log.warning(f"DeepSeek init failed: {e}")
            
    async def _init_openrouter(self):
        """Initialize OpenRouter provider (free tier)"""
        try:
            from openai import OpenAI
            api_key = self.config.get_api_key("openrouter")
            if api_key:
                self._providers["openrouter"] = {
                    "client": OpenAI(
                        api_key=api_key,
                        base_url="https://openrouter.ai/api/v1"
                    ),
                    "models": [
                        "google/gemini-2.0-flash-lite:free",
                        "meta-llama/llama-3.3-70b-instruct:free",
                        "mistralai/mixtral-8x7b-instruct:free"
                    ]
                }
                log.info("✅ OpenRouter provider ready (free tier)")
        except Exception as e:
            log.warning(f"OpenRouter init failed: {e}")
            
    async def _init_ollama(self):
        """Initialize Ollama for offline"""
        try:
            import requests
            ollama_url = self.config.get("ai.ollama_url", "http://localhost:11434")
            
            # Test connection
            try:
                response = requests.get(f"{ollama_url}/api/tags", timeout=2)
                if response.status_code == 200:
                    models = response.json().get("models", [])
                    self._providers["ollama"] = {
                        "url": ollama_url,
                        "models": [m["name"] for m in models],
                        "available": True
                    }
                    log.info(f"✅ Ollama provider ready ({len(models)} models)")
            except:
                log.info("⚠️ Ollama not running - offline mode unavailable")
                self._providers["ollama"] = {"available": False}
                
        except Exception as e:
            log.warning(f"Ollama init failed: {e}")
            
    async def generate(self, prompt: str, context: List[ChatMessage] = None,
                      prefer_offline: bool = False) -> AIResponse:
        """Generate AI response with fallback"""
        
        # Try offline first if preferred or no internet
        if prefer_offline and "ollama" in self._providers:
            response = await self._generate_ollama(prompt, context)
            if response and not response.error:
                return response
                
        # Try online providers in order
        providers_order = ["openrouter", "openai", "anthropic", "google", "deepseek"]
        
        for provider_name in providers_order:
            if provider_name in self._providers:
                response = await self._generate_with_provider(provider_name, prompt, context)
                if response and not response.error:
                    return response
                    
        # Last resort: Ollama
        if "ollama" in self._providers:
            return await self._generate_ollama(prompt, context)
            
        return AIResponse(
            text="Sorry, no AI providers are available.",
            provider="none",
            model="none",
            latency_ms=0,
            error="No providers available"
        )
        
    async def _generate_with_provider(self, provider: str, prompt: str,
                                     context: List[ChatMessage] = None) -> AIResponse:
        """Generate with specific provider"""
        start_time = time.time()
        
        try:
            if provider == "openai":
                return await self._generate_openai(prompt, context, start_time)
            elif provider == "anthropic":
                return await self._generate_anthropic(prompt, context, start_time)
            elif provider == "google":
                return await self._generate_google(prompt, context, start_time)
            elif provider == "deepseek":
                return await self._generate_deepseek(prompt, context, start_time)
            elif provider == "openrouter":
                return await self._generate_openrouter(prompt, context, start_time)
        except Exception as e:
            log.error(f"Provider {provider} error: {e}")
            return AIResponse(
                text="", provider=provider, model="unknown",
                latency_ms=int((time.time() - start_time) * 1000),
                error=str(e)
            )
            
    async def _generate_openai(self, prompt: str, context: List[ChatMessage],
                              start_time: float) -> AIResponse:
        """Generate with OpenAI"""
        client = self._providers["openai"]["client"]
        model = self.config.get("ai.model", "gpt-4o-mini")
        
        messages = []
        if context:
            messages.extend([{"role": m.role, "content": m.content} for m in context])
        messages.append({"role": "user", "content": prompt})
        
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=500
            )
            
            return AIResponse(
                text=response.choices[0].message.content,
                provider="openai",
                model=model,
                latency_ms=int((time.time() - start_time) * 1000)
            )
        except Exception as e:
            return AIResponse(text="", provider="openai", model=model,
                            latency_ms=int((time.time() - start_time) * 1000), error=str(e))
                            
    async def _generate_anthropic(self, prompt: str, context: List[ChatMessage],
                                  start_time: float) -> AIResponse:
        """Generate with Anthropic Claude"""
        client = self._providers["anthropic"]["client"]
        model = "claude-3-5-sonnet-latest"
        
        messages = []
        if context:
            messages.extend([{"role": m.role, "content": m.content} for m in context])
        messages.append({"role": "user", "content": prompt})
        
        try:
            response = client.messages.create(
                model=model,
                max_tokens=500,
                messages=messages
            )
            
            return AIResponse(
                text=response.content[0].text,
                provider="anthropic",
                model=model,
                latency_ms=int((time.time() - start_time) * 1000)
            )
        except Exception as e:
            return AIResponse(text="", provider="anthropic", model=model,
                            latency_ms=int((time.time() - start_time) * 1000), error=str(e))
                            
    async def _generate_google(self, prompt: str, context: List[ChatMessage],
                              start_time: float) -> AIResponse:
        """Generate with Google Gemini"""
        client = self._providers["google"]["client"]
        model = self._providers["google"]["models"][0]
        
        try:
            model_instance = client.generate_model(model)
            response = model_instance.generate_content(prompt)
            
            return AIResponse(
                text=response.text,
                provider="google",
                model=model,
                latency_ms=int((time.time() - start_time) * 1000)
            )
        except Exception as e:
            return AIResponse(text="", provider="google", model=model,
                            latency_ms=int((time.time() - start_time) * 1000), error=str(e))
                            
    async def _generate_deepseek(self, prompt: str, context: List[ChatMessage],
                                start_time: float) -> AIResponse:
        """Generate with DeepSeek"""
        client = self._providers["deepseek"]["client"]
        model = "deepseek-chat"
        
        messages = []
        if context:
            messages.extend([{"role": m.role, "content": m.content} for m in context])
        messages.append({"role": "user", "content": prompt})
        
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages
            )
            
            return AIResponse(
                text=response.choices[0].message.content,
                provider="deepseek",
                model=model,
                latency_ms=int((time.time() - start_time) * 1000)
            )
        except Exception as e:
            return AIResponse(text="", provider="deepseek", model=model,
                            latency_ms=int((time.time() - start_time) * 1000), error=str(e))
                            
    async def _generate_openrouter(self, prompt: str, context: List[ChatMessage],
                                  start_time: float) -> AIResponse:
        """Generate with OpenRouter (free tier)"""
        client = self._providers["openrouter"]["client"]
        model = self.config.get("ai.model", "google/gemini-2.0-flash-lite:free")
        
        messages = []
        if context:
            messages.extend([{"role": m.role, "content": m.content} for m in context])
        messages.append({"role": "user", "content": prompt})
        
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages
            )
            
            return AIResponse(
                text=response.choices[0].message.content,
                provider="openrouter",
                model=model,
                latency_ms=int((time.time() - start_time) * 1000)
            )
        except Exception as e:
            return AIResponse(text="", provider="openrouter", model=model,
                            latency_ms=int((time.time() - start_time) * 1000), error=str(e))
                            
    async def _generate_ollama(self, prompt: str, context: List[ChatMessage] = None) -> AIResponse:
        """Generate with local Ollama"""
        import requests
        
        ollama_info = self._providers.get("ollama", {})
        if not ollama_info.get("available", False):
            return AIResponse(text="", provider="ollama", model="none",
                            latency_ms=0, error="Ollama not available")
            
        url = f"{ollama_info['url']}/api/generate"
        model = self.config.get("ai.offline_model", "phi3:latest")
        
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False
        }
        
        start_time = time.time()
        
        try:
            response = requests.post(url, json=payload, timeout=60)
            
            if response.status_code == 200:
                data = response.json()
                return AIResponse(
                    text=data.get("response", ""),
                    provider="ollama",
                    model=model,
                    latency_ms=int((time.time() - start_time) * 1000)
                )
        except Exception as e:
            log.error(f"Ollama error: {e}")
            
        return AIResponse(text="", provider="ollama", model=model,
                        latency_ms=int((time.time() - start_time) * 1000), error=str(e))
