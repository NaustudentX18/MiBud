# Changelog

All notable changes to MiBud will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased] - v2.0.0

Major intelligence uplift for MiBud.

### Added
- **Long-term memory (`ai/memory.py`)** — local SQLite store with durable facts,
  user profile, session summaries, and semantic recall. Ships with a zero-dep
  hashing embedder (256-d char n-grams) and auto-upgrades to Ollama
  `nomic-embed-text` (768-d) when available. Near-duplicate facts are merged on
  write (cosine >= 0.92). Recall is vectorised to a single matmul across all
  fact vectors for Pi-Zero-friendly latency.
- **Fact extractor** — regex-based first-person extractor that pulls names,
  locations, likes/dislikes, allergies, routines, timezone from user turns and
  stores them automatically.
- **Tool use / function calling (`ai/tools.py`)** — decorator-driven provider-
  agnostic tool layer. 20+ built-ins (time, battery, timers, reminders, notes,
  memory remember/recall, camera describe_scene, personality switcher, Home
  Assistant service calls, GPIO, DuckDuckGo web search, system info). Provider
  adapters for OpenAI / Anthropic / Google.
- **Streaming LLM -> sentence TTS (`ai/streaming.py`)** — token-level sentence
  splitter with abbreviation handling, bounded speak-queue, and first-sentence
  latency stats. Sub-second audio start on openrouter/openai.
- **Proactive engine (`core/proactive.py`)** — battery low/critical alerts with
  re-arming on charge, reminder firing, timer monitoring, morning greeting,
  idle check-ins, quiet hours (with wrap-around).
- **Power profiles (`core/power.py`)** — ECO / BALANCED / PERFORMANCE with
  automatic battery- and charge-driven selection. Every subsystem reacts via
  subscribe() — brightness, poll intervals, max tokens, offline preferences.
- **Hardened router (`ai/router.py`)** — circuit breaker per provider, exponential
  backoff retries, cached connectivity probe, per-provider moving-average
  metrics, tool-call iteration loop, unified streaming interface, thread-pool
  offload of every sync SDK call.
- **Web API v2 (`web/api_v2.py`)** — Flask blueprint exposing memory, tools,
  power, provider-health endpoints, SSE streaming chat at
  `/api/chat/stream`, and an unauth'd `/api/health` suitable for watchdogs.
- **41-test suite** — coverage for tool schema generation, memory dedup/recall,
  sentence buffering, power profile transitions, proactive engine edge cases,
  and router reliability (circuit breaker + retry).

### Changed
- `ai/router.py` rewritten end-to-end: async tool loop, streaming support,
  retries, breakers, connectivity caching, metrics.
- `ai/conversation.py` upgraded to inject memory context into the system
  prompt, run fact extraction after each user turn, stream through the new
  TTS pipeline, and end-session summarise on stop.
- `core/main.py` boots memory, power manager, proactive engine, and binds
  services into the web API.
- `core/config.py` bumped to version 2 with a `_migrate_v1_to_v2()` shim that
  preserves user settings; adds `features.enable_memory|tools|streaming|
  proactive|power_manager`.

## [Unreleased] - v1.0.0

### Added
- **Core System**
  - State machine (idle, listening, thinking, speaking, error, sleep)
  - Event bus for inter-component communication
  - Configuration management with 20+ settings
  - Signal handling for graceful shutdown

- **Hardware Drivers**
  - Display driver (ST7789 240x280, 20+ themes)
  - Audio manager (WM8960 codec + ALSA)
  - Button manager (GPIO with short/long/hold detection)
  - Battery manager (PiSugar 3 monitoring)
  - LED manager (RGB with themes)
  - Camera manager (Picamera2, Picamera, USB support)

- **AI System**
  - Multi-provider router (OpenAI, Anthropic, Google, DeepSeek, Ollama, OpenRouter)
  - Wake word detection (openWakeWord + VAD fallback)
  - Speaker recognition (voice embeddings)
  - Anomaly detection (pattern monitoring, alerts)
  - Vision support (image understanding)

- **Personalities**
  - 20 preset personalities (Assistant, Chef, Hacker, DJ, Mentor, etc.)
  - Custom personality creator with web UI
  - Personality manager for CRUD operations

- **Web Interface**
  - Flask server with REST API
  - Setup wizard (8-step onboarding)
  - Dashboard with chat, settings, system monitoring
  - API endpoints for all features

- **Utilities**
  - Timer manager
  - Reminder manager
  - Note manager
  - System info

- **Home Automation**
  - GPIO controller
  - Home Assistant integration

- **Multi-Device Sync**
  - zeroconf-based device discovery
  - Peer-to-peer settings sync
  - Automatic network discovery

### Features
- Full offline operation with Ollama
- Cloud fallback when offline
- Privacy-first architecture
- 8+ hour battery life
- Beautiful display animations
- Physical button controls

---

## [v0.1.0] - Initial Release

### Added
- Initial project structure
- Basic WhisPlay HAT support
- Personality system foundation
- Web interface skeleton

---

## Roadmap

### v1.1
- [ ] Camera module integration with AI
- [ ] Advanced TTS options (Piper, Coqui)
- [ ] Wake word model fine-tuning
- [ ] Community personality sharing

### v1.2
- [ ] Multi-device chat sync
- [ ] Advanced speaker verification
- [ ] Gesture recognition
- [ ] Voice cloning

### Future
- [ ] Custom hardware case designs
- [ ] Mobile companion app
- [ ] Home Assistant integration improvements
- [ ] IFTTT/applet support
