# Changelog

All notable changes to MiBud will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

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
