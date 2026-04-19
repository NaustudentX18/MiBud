"""
MiBud AI - Router
Multi-Provider AI Routing with Offline Fallback, Retry, Circuit Breakers,
Streaming, and Tool Use.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

import aiohttp

from ai.tools import (
    ToolCall,
    ToolRegistry,
    ToolResult,
    get_registry,
    run_tool_calls,
)

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
    tool_calls: List[ToolCall] = field(default_factory=list)
    tool_results: List[ToolResult] = field(default_factory=list)


@dataclass
class ChatMessage:
    """Chat message"""
    role: str  # system, user, assistant, tool
    content: str
    name: Optional[str] = None            # for tool messages
    tool_call_id: Optional[str] = None    # OpenAI tool reply correlation


# ---------------------------------------------------------------------------
# Reliability: circuit breaker + retries
# ---------------------------------------------------------------------------


@dataclass
class CircuitBreaker:
    """Simple fail-then-cool breaker: skip a provider for N seconds after
    consecutive failures."""
    failures: int = 0
    max_failures: int = 3
    cool_seconds: float = 30.0
    opened_at: float = 0.0

    def allow(self) -> bool:
        if self.failures < self.max_failures:
            return True
        if time.monotonic() - self.opened_at >= self.cool_seconds:
            # Half-open: one try is allowed.
            return True
        return False

    def on_success(self) -> None:
        self.failures = 0
        self.opened_at = 0.0

    def on_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.max_failures:
            self.opened_at = time.monotonic()


async def _with_retry(
    call: Callable[[], Any],
    *,
    attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 4.0,
) -> Any:
    """Run `call` with exponential backoff.

    Raises the final exception if every attempt fails.
    """
    last_exc: Optional[BaseException] = None
    for i in range(attempts):
        try:
            result = call()
            if asyncio.iscoroutine(result):
                result = await result
            return result
        except Exception as e:
            last_exc = e
            if i == attempts - 1:
                break
            delay = min(max_delay, base_delay * (2 ** i))
            log.debug(f"retry #{i + 1} after {delay:.1f}s: {e}")
            await asyncio.sleep(delay)
    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


class AIRouter:
    """Routes AI requests to appropriate provider with fallback"""

    def __init__(self, config, tool_registry: Optional[ToolRegistry] = None):
        self.config = config
        self.is_initialized = False
        self._providers: Dict[str, Any] = {}
        self._current_provider = None
        self._offline_provider = AIProvider.OLLAMA
        self._online_provider = AIProvider.OPENROUTER
        self._breakers: Dict[str, CircuitBreaker] = {}
        self._tools = tool_registry  # Use get_registry() lazily if None.
        self._max_tool_iterations = 4
        self._last_internet_check = 0.0
        self._last_internet_ok = True
        self._internet_cache_seconds = 30.0
        # Lightweight metrics for observability.
        self._metrics: Dict[str, Dict[str, float]] = {}

    # ---- public configuration ----------------------------------------

    def attach_tools(self, registry: ToolRegistry) -> None:
        self._tools = registry

    def _registry(self) -> ToolRegistry:
        return self._tools or get_registry()

    def _breaker(self, name: str) -> CircuitBreaker:
        b = self._breakers.get(name)
        if b is None:
            b = self._breakers[name] = CircuitBreaker()
        return b

    def provider_health(self) -> Dict[str, Dict[str, Any]]:
        return {
            name: {
                "failures": b.failures,
                "open": b.failures >= b.max_failures,
                "cool_remaining": max(0.0, b.opened_at + b.cool_seconds - time.monotonic())
                if b.opened_at else 0.0,
                **self._metrics.get(name, {}),
            }
            for name, b in self._breakers.items()
        }

    def _record_metric(self, provider: str, latency_ms: int, ok: bool) -> None:
        m = self._metrics.setdefault(provider, {
            "calls": 0, "wins": 0, "losses": 0, "avg_ms": 0.0, "last_ms": 0.0,
        })
        m["calls"] += 1
        m["wins" if ok else "losses"] += 1
        # Exponential moving average.
        m["avg_ms"] = (0.8 * m["avg_ms"] + 0.2 * latency_ms) if m["avg_ms"] else float(latency_ms)
        m["last_ms"] = float(latency_ms)

    # ---- init --------------------------------------------------------

    async def initialize(self):
        """Initialize AI providers"""
        log.info("🧠 Initializing AI router...")

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

        await self._init_ollama()

        default = self.config.get("ai.default_provider", "openrouter")
        self._current_provider = default

        self.is_initialized = True
        log.info(f"✅ AI router initialized with {len(self._providers)} providers")

    async def _init_openai(self):
        try:
            from openai import OpenAI
            api_key = self.config.get_api_key("openai")
            if api_key:
                self._providers["openai"] = {
                    "client": OpenAI(api_key=api_key),
                    "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
                    "supports_tools": True,
                }
                log.info("✅ OpenAI provider ready")
        except Exception as e:
            log.warning(f"OpenAI init failed: {e}")

    async def _init_anthropic(self):
        try:
            from anthropic import Anthropic
            api_key = self.config.get_api_key("anthropic")
            if api_key:
                self._providers["anthropic"] = {
                    "client": Anthropic(api_key=api_key),
                    "models": ["claude-3-5-sonnet-latest", "claude-3-haiku-latest"],
                    "supports_tools": True,
                }
                log.info("✅ Anthropic provider ready")
        except Exception as e:
            log.warning(f"Anthropic init failed: {e}")

    async def _init_google(self):
        try:
            import google.generativeai as genai
            api_key = self.config.get_api_key("google")
            if api_key:
                genai.configure(api_key=api_key)
                self._providers["google"] = {
                    "client": genai,
                    "models": ["gemini-2.0-flash", "gemini-pro"],
                    "supports_tools": True,
                }
                log.info("✅ Google provider ready")
        except Exception as e:
            log.warning(f"Google init failed: {e}")

    async def _init_deepseek(self):
        try:
            from openai import OpenAI
            api_key = self.config.get_api_key("deepseek")
            if api_key:
                self._providers["deepseek"] = {
                    "client": OpenAI(api_key=api_key, base_url="https://api.deepseek.com"),
                    "models": ["deepseek-chat"],
                    "supports_tools": True,
                }
                log.info("✅ DeepSeek provider ready")
        except Exception as e:
            log.warning(f"DeepSeek init failed: {e}")

    async def _init_openrouter(self):
        try:
            from openai import OpenAI
            api_key = self.config.get_api_key("openrouter")
            if api_key:
                self._providers["openrouter"] = {
                    "client": OpenAI(
                        api_key=api_key,
                        base_url="https://openrouter.ai/api/v1",
                    ),
                    "models": [
                        "google/gemini-2.0-flash-lite:free",
                        "meta-llama/llama-3.3-70b-instruct:free",
                        "mistralai/mixtral-8x7b-instruct:free",
                    ],
                    "supports_tools": True,
                }
                log.info("✅ OpenRouter provider ready (free tier)")
        except Exception as e:
            log.warning(f"OpenRouter init failed: {e}")

    async def _init_ollama(self):
        try:
            ollama_url = self.config.get("ai.ollama_url", "http://localhost:11434")
            try:
                timeout = aiohttp.ClientTimeout(total=2)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(f"{ollama_url}/api/tags") as response:
                        if response.status == 200:
                            data = await response.json()
                            models = data.get("models", [])
                            self._providers["ollama"] = {
                                "url": ollama_url,
                                "models": [m["name"] for m in models],
                                "available": True,
                                "supports_tools": False,
                            }
                            log.info(f"✅ Ollama provider ready ({len(models)} models)")
                            return
            except Exception:
                pass

            log.info("⚠️ Ollama not running - offline mode unavailable")
            self._providers["ollama"] = {"available": False, "url": ollama_url}

        except Exception as e:
            log.warning(f"Ollama init failed: {e}")

    # ---- connectivity -----------------------------------------------

    async def _check_internet_connectivity(self) -> bool:
        """Cache-backed connectivity probe."""
        now = time.monotonic()
        if now - self._last_internet_check < self._internet_cache_seconds:
            return self._last_internet_ok
        self._last_internet_check = now
        try:
            timeout = aiohttp.ClientTimeout(total=3)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get("https://1.1.1.1/", ssl=False) as resp:
                    self._last_internet_ok = resp.status < 500
        except Exception:
            self._last_internet_ok = False
        return self._last_internet_ok

    # ---- provider helpers -------------------------------------------

    def _provider_order(self, prefer_offline: bool) -> List[str]:
        default = self.config.get("ai.default_provider", "openrouter")
        preferred: List[str] = []
        if prefer_offline:
            preferred = ["ollama", default, "openrouter", "openai", "anthropic", "google", "deepseek"]
        else:
            preferred = [default, "openrouter", "openai", "anthropic", "google", "deepseek", "ollama"]
        seen: set = set()
        order: List[str] = []
        for name in preferred:
            if name in self._providers and name not in seen:
                seen.add(name)
                order.append(name)
        return order

    # ---- generate -----------------------------------------------------

    async def generate(
        self,
        prompt: str,
        context: List[ChatMessage] = None,
        prefer_offline: bool = False,
        tools: Optional[List[str]] = None,
        max_tokens: Optional[int] = None,
    ) -> AIResponse:
        """Generate response with fallback + optional tool use."""
        if not prefer_offline and not await self._check_internet_connectivity():
            log.info("🌐 No internet — switching to offline mode")
            prefer_offline = True

        messages = list(context or [])
        messages.append(ChatMessage(role="user", content=prompt))

        for provider_name in self._provider_order(prefer_offline):
            breaker = self._breaker(provider_name)
            if not breaker.allow():
                log.debug(f"breaker open, skipping {provider_name}")
                continue

            if tools and self._providers[provider_name].get("supports_tools"):
                response = await self._generate_with_tools(
                    provider_name, messages, tools, max_tokens=max_tokens,
                )
            elif provider_name == "ollama":
                response = await self._generate_ollama(prompt, context)
            else:
                response = await self._invoke_plain(
                    provider_name, messages, max_tokens=max_tokens,
                )

            if response and not response.error:
                breaker.on_success()
                self._record_metric(provider_name, response.latency_ms, True)
                return response
            breaker.on_failure()
            if response is not None:
                self._record_metric(provider_name, response.latency_ms, False)

        return AIResponse(
            text="Sorry, no AI providers are available.",
            provider="none",
            model="none",
            latency_ms=0,
            error="No providers available",
        )

    # ---- streaming ---------------------------------------------------

    async def generate_stream(
        self,
        prompt: str,
        context: List[ChatMessage] = None,
        prefer_offline: bool = False,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """Yield text chunks from the first healthy provider.

        Does NOT support tool calls — use `generate()` for that.
        """
        from ai.streaming import anthropic_stream, ollama_stream, openai_stream

        if not prefer_offline and not await self._check_internet_connectivity():
            prefer_offline = True
        messages = list(context or [])
        messages.append(ChatMessage(role="user", content=prompt))

        max_toks = max_tokens or self.config.get("tuning.ai_max_tokens", 500)

        for provider_name in self._provider_order(prefer_offline):
            breaker = self._breaker(provider_name)
            if not breaker.allow():
                continue
            try:
                p = self._providers[provider_name]
                msg_payload = [{"role": m.role, "content": m.content} for m in messages]
                if provider_name == "ollama":
                    if not p.get("available"):
                        continue
                    prompt_text = _messages_to_prompt(messages)
                    model = self.config.get("ai.offline_model", "phi3:latest")
                    iterator = ollama_stream(p["url"], model, prompt_text)
                elif provider_name == "anthropic":
                    system = next((m.content for m in messages if m.role == "system"), "")
                    non_system = [m for m in messages if m.role != "system"]
                    iterator = anthropic_stream(
                        p["client"],
                        model="claude-3-5-sonnet-latest",
                        messages=[{"role": m.role, "content": m.content} for m in non_system],
                        max_tokens=max_toks,
                        system=system,
                    )
                else:
                    model = self._model_for(provider_name)
                    iterator = openai_stream(p["client"], model, msg_payload, max_tokens=max_toks)
                any_yielded = False
                async for chunk in iterator:
                    any_yielded = True
                    yield chunk
                if any_yielded:
                    breaker.on_success()
                    return
            except Exception as e:
                log.warning(f"stream from {provider_name} failed: {e}")
                breaker.on_failure()
                continue

    # ---- tool-use loop -----------------------------------------------

    async def _generate_with_tools(
        self,
        provider_name: str,
        messages: List[ChatMessage],
        tool_names: List[str],
        *,
        max_tokens: Optional[int] = None,
    ) -> AIResponse:
        """Multi-iteration tool-use loop for OpenAI-compatible providers.

        Only OpenAI-style `tools` + `tool_calls` is implemented here; other
        providers fall back to plain generate.
        """
        if provider_name not in ("openai", "openrouter", "deepseek"):
            # Other providers not wired for tool-use yet — fall back.
            return await self._invoke_plain(provider_name, messages, max_tokens=max_tokens)

        client = self._providers[provider_name]["client"]
        model = self._model_for(provider_name)
        registry = self._registry()
        tool_specs = [registry.get(n) for n in tool_names if registry.get(n)]
        tools_payload = [t.to_openai() for t in tool_specs]

        history = [
            {"role": m.role, "content": m.content, **({"name": m.name} if m.name else {})}
            for m in messages
        ]

        start = time.time()
        all_calls: List[ToolCall] = []
        all_results: List[ToolResult] = []

        for _ in range(self._max_tool_iterations):
            def _call():
                return client.chat.completions.create(
                    model=model,
                    messages=history,
                    tools=tools_payload,
                    tool_choice="auto",
                    max_tokens=max_tokens or self.config.get("tuning.ai_max_tokens", 500),
                )

            try:
                resp = await _with_retry(lambda: asyncio.to_thread(_call))
            except Exception as e:
                return AIResponse(
                    text="", provider=provider_name, model=model,
                    latency_ms=int((time.time() - start) * 1000), error=str(e),
                )

            msg = resp.choices[0].message
            tcalls = getattr(msg, "tool_calls", None) or []
            if not tcalls:
                content = msg.content or ""
                return AIResponse(
                    text=content,
                    provider=provider_name,
                    model=model,
                    latency_ms=int((time.time() - start) * 1000),
                    tool_calls=all_calls,
                    tool_results=all_results,
                )

            # Record the assistant's tool-call message into the running history.
            history.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in tcalls
                ],
            })

            calls: List[ToolCall] = []
            for tc in tcalls:
                import json as _json
                try:
                    args = _json.loads(tc.function.arguments or "{}")
                except Exception:
                    args = {}
                calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

            all_calls.extend(calls)
            results = await run_tool_calls(calls, registry=registry)
            all_results.extend(results)

            for r in results:
                history.append({
                    "role": "tool",
                    "tool_call_id": r.id,
                    "name": r.name,
                    "content": _tool_result_to_str(r),
                })

        return AIResponse(
            text="(tool-call loop exhausted without a final answer)",
            provider=provider_name,
            model=model,
            latency_ms=int((time.time() - start) * 1000),
            tool_calls=all_calls,
            tool_results=all_results,
            error="max_iterations",
        )

    # ---- plain (non-tool) generation --------------------------------

    async def _invoke_plain(
        self,
        provider_name: str,
        messages: List[ChatMessage],
        *,
        max_tokens: Optional[int] = None,
    ) -> AIResponse:
        start = time.time()
        try:
            if provider_name == "anthropic":
                return await self._generate_anthropic(messages, start, max_tokens)
            if provider_name == "google":
                return await self._generate_google(messages, start, max_tokens)
            if provider_name == "ollama":
                # Convert messages back to a prompt + context list.
                user = next((m for m in reversed(messages) if m.role == "user"), None)
                ctx = [m for m in messages if m is not user]
                return await self._generate_ollama(user.content if user else "", ctx)
            return await self._generate_openai_compatible(provider_name, messages, start, max_tokens)
        except Exception as e:
            log.error(f"Provider {provider_name} error: {e}")
            return AIResponse(
                text="", provider=provider_name, model="unknown",
                latency_ms=int((time.time() - start) * 1000), error=str(e),
            )

    async def _generate_openai_compatible(
        self,
        provider_name: str,
        messages: List[ChatMessage],
        start_time: float,
        max_tokens: Optional[int],
    ) -> AIResponse:
        client = self._providers[provider_name]["client"]
        model = self._model_for(provider_name)
        payload = [{"role": m.role, "content": m.content} for m in messages]

        def _call():
            return client.chat.completions.create(
                model=model,
                messages=payload,
                max_tokens=max_tokens or self.config.get("tuning.ai_max_tokens", 500),
            )
        try:
            response = await _with_retry(lambda: asyncio.to_thread(_call))
        except Exception as e:
            return AIResponse(
                text="", provider=provider_name, model=model,
                latency_ms=int((time.time() - start_time) * 1000), error=str(e),
            )
        return AIResponse(
            text=response.choices[0].message.content or "",
            provider=provider_name,
            model=model,
            latency_ms=int((time.time() - start_time) * 1000),
        )

    async def _generate_anthropic(
        self,
        messages: List[ChatMessage],
        start_time: float,
        max_tokens: Optional[int],
    ) -> AIResponse:
        client = self._providers["anthropic"]["client"]
        model = "claude-3-5-sonnet-latest"
        system = next((m.content for m in messages if m.role == "system"), "")
        non_system = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]

        def _call():
            return client.messages.create(
                model=model,
                max_tokens=max_tokens or self.config.get("tuning.ai_max_tokens", 500),
                system=system or None,
                messages=non_system,
            )
        try:
            response = await _with_retry(lambda: asyncio.to_thread(_call))
        except Exception as e:
            return AIResponse(
                text="", provider="anthropic", model=model,
                latency_ms=int((time.time() - start_time) * 1000), error=str(e),
            )
        return AIResponse(
            text=response.content[0].text if response.content else "",
            provider="anthropic",
            model=model,
            latency_ms=int((time.time() - start_time) * 1000),
        )

    async def _generate_google(
        self,
        messages: List[ChatMessage],
        start_time: float,
        max_tokens: Optional[int],
    ) -> AIResponse:
        client = self._providers["google"]["client"]
        model = self._providers["google"]["models"][0]
        prompt = _messages_to_prompt(messages)

        def _call():
            instance = client.GenerativeModel(model)
            return instance.generate_content(prompt)
        try:
            response = await _with_retry(lambda: asyncio.to_thread(_call))
        except Exception as e:
            return AIResponse(
                text="", provider="google", model=model,
                latency_ms=int((time.time() - start_time) * 1000), error=str(e),
            )
        return AIResponse(
            text=getattr(response, "text", "") or "",
            provider="google",
            model=model,
            latency_ms=int((time.time() - start_time) * 1000),
        )

    async def _generate_ollama(self, prompt: str, context: List[ChatMessage] = None) -> AIResponse:
        ollama_info = self._providers.get("ollama", {})
        if not ollama_info.get("available", False):
            return AIResponse(text="", provider="ollama", model="none",
                              latency_ms=0, error="Ollama not available")

        url = f"{ollama_info['url']}/api/generate"
        model = self.config.get("ai.offline_model", "phi3:latest")
        system = ""
        history = ""
        for m in context or []:
            if m.role == "system":
                system = m.content
            else:
                history += f"{m.role}: {m.content}\n"
        full_prompt = (system + "\n" + history + f"user: {prompt}\nassistant:").strip()

        start_time = time.time()
        try:
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, json={
                    "model": model, "prompt": full_prompt, "stream": False,
                }) as response:
                    if response.status == 200:
                        data = await response.json()
                        return AIResponse(
                            text=data.get("response", ""),
                            provider="ollama",
                            model=model,
                            latency_ms=int((time.time() - start_time) * 1000),
                        )
                    return AIResponse(
                        text="", provider="ollama", model=model,
                        latency_ms=int((time.time() - start_time) * 1000),
                        error=f"status {response.status}",
                    )
        except Exception as e:
            log.error(f"Ollama error: {e}")
            return AIResponse(
                text="", provider="ollama", model=model,
                latency_ms=int((time.time() - start_time) * 1000), error=str(e),
            )

    def _model_for(self, provider_name: str) -> str:
        if provider_name == "openai":
            return self.config.get("ai.model_openai", "gpt-4o-mini")
        if provider_name == "openrouter":
            return self.config.get("ai.model", "google/gemini-2.0-flash-lite:free")
        if provider_name == "deepseek":
            return "deepseek-chat"
        return self.config.get("ai.model", "gpt-4o-mini")

    # ---- vision ------------------------------------------------------

    async def generate_with_vision(
        self,
        prompt: str,
        image_data: bytes,
        context: List[ChatMessage] = None,
    ) -> AIResponse:
        start_time = time.time()
        providers_with_vision = ["openai", "anthropic", "google", "openrouter"]

        for provider_name in providers_with_vision:
            if provider_name not in self._providers:
                continue
            breaker = self._breaker(provider_name)
            if not breaker.allow():
                continue
            try:
                resp = await self._generate_vision_with_provider(
                    provider_name, prompt, image_data, context, start_time,
                )
                if resp and not resp.error:
                    breaker.on_success()
                    return resp
                breaker.on_failure()
            except Exception as e:
                log.warning(f"Vision {provider_name} failed: {e}")
                breaker.on_failure()

        return AIResponse(
            text="Sorry, vision processing is not available.",
            provider="none",
            model="none",
            latency_ms=int((time.time() - start_time) * 1000),
            error="No vision-capable provider available",
        )

    async def _generate_vision_with_provider(self, provider, prompt, image_data, context, start):
        if provider == "openai":
            return await self._generate_vision_openai(prompt, image_data, context, start)
        if provider == "anthropic":
            return await self._generate_vision_anthropic(prompt, image_data, context, start)
        if provider == "google":
            return await self._generate_vision_google(prompt, image_data, start)
        if provider == "openrouter":
            return await self._generate_vision_openrouter(prompt, image_data, context, start)
        raise ValueError(f"no vision adapter for {provider}")

    async def _generate_vision_openai(self, prompt, image_data, context, start_time):
        import base64
        client = self._providers["openai"]["client"]
        model = "gpt-4o"
        image_b64 = base64.b64encode(image_data).decode()
        messages = [{"role": m.role, "content": m.content} for m in (context or [])]
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            ],
        })
        def _call():
            return client.chat.completions.create(model=model, messages=messages, max_tokens=500)
        response = await _with_retry(lambda: asyncio.to_thread(_call))
        return AIResponse(
            text=response.choices[0].message.content or "",
            provider="openai", model=model,
            latency_ms=int((time.time() - start_time) * 1000),
        )

    async def _generate_vision_anthropic(self, prompt, image_data, context, start_time):
        import base64
        client = self._providers["anthropic"]["client"]
        model = "claude-3-5-sonnet-latest"
        image_b64 = base64.b64encode(image_data).decode()
        messages = [{"role": m.role, "content": m.content} for m in (context or []) if m.role != "system"]
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
            ],
        })
        def _call():
            return client.messages.create(model=model, max_tokens=500, messages=messages)
        response = await _with_retry(lambda: asyncio.to_thread(_call))
        return AIResponse(
            text=response.content[0].text if response.content else "",
            provider="anthropic", model=model,
            latency_ms=int((time.time() - start_time) * 1000),
        )

    async def _generate_vision_google(self, prompt, image_data, start_time):
        from PIL import Image
        import io
        client = self._providers["google"]["client"]
        model_name = "gemini-2.0-flash"
        def _call():
            image = Image.open(io.BytesIO(image_data))
            instance = client.GenerativeModel(model_name)
            return instance.generate_content([prompt, image])
        response = await _with_retry(lambda: asyncio.to_thread(_call))
        return AIResponse(
            text=getattr(response, "text", "") or "",
            provider="google", model=model_name,
            latency_ms=int((time.time() - start_time) * 1000),
        )

    async def _generate_vision_openrouter(self, prompt, image_data, context, start_time):
        import base64
        client = self._providers["openrouter"]["client"]
        model = "google/gemini-2.0-flash"
        image_b64 = base64.b64encode(image_data).decode()
        messages = [{"role": m.role, "content": m.content} for m in (context or [])]
        messages.append({
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            ],
        })
        def _call():
            return client.chat.completions.create(model=model, messages=messages)
        response = await _with_retry(lambda: asyncio.to_thread(_call))
        return AIResponse(
            text=response.choices[0].message.content or "",
            provider="openrouter", model=model,
            latency_ms=int((time.time() - start_time) * 1000),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _messages_to_prompt(messages: List[ChatMessage]) -> str:
    parts = []
    for m in messages:
        parts.append(f"{m.role}: {m.content}")
    return "\n".join(parts)


def _tool_result_to_str(r: ToolResult) -> str:
    import json as _json
    if r.ok:
        try:
            return _json.dumps(r.content, ensure_ascii=False)
        except Exception:
            return str(r.content)
    return _json.dumps({"error": r.error})
