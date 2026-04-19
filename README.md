<div align="center">

# 🌱 MiBud

### *Your Privacy-First AI Companion — Pocket-Sized and Always With You*

[![CI](https://github.com/NaustudentX18/MiBud/actions/workflows/ci.yml/badge.svg)](https://github.com/NaustudentX18/MiBud/actions/workflows/ci.yml)
![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi%20Zero%202%20W-c51a4a?logo=raspberry-pi&logoColor=white)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-22c55e)
![Status](https://img.shields.io/badge/status-beta-f59e0b)

**MiBud** is a lightweight, privacy-focused AI assistant built for low-power Raspberry Pi deployments.  
Works **fully offline** with local models — or connects to cloud AI when you want it.  
Runs on your hardware, stores nothing in the cloud, and puts *you* in control.

[Quick Start](#-quick-start) · [Features](#-features) · [Hardware](#-hardware-target) · [Docs](#-documentation) · [Contributing](#-contributing)

</div>

---

## ✨ Why MiBud?

> **Tiny device. Big personality. Zero compromise on privacy.**

| | |
|---|---|
| 🔒 **Privacy First** | 100 % offline mode — your conversations never leave your device |
| 🧠 **20+ Personalities** | From Chef to Therapist — or build your own via the web UI |
| 🔋 **Battery-Aware** | Designed for 8+ h portable use with PiSugar 3 |
| ⚡ **Fast Startup** | Boots to ready in ~20 s on Pi Zero 2 W |
| 🌐 **Multi-Provider AI** | OpenAI · Anthropic · Google · DeepSeek · OpenRouter · Ollama |
| 📺 **Beautiful Display** | 240×280 ST7789 with 20+ themes and smooth animations |

---

## 🧩 Hardware Target

| Component | Model |
|-----------|-------|
| 🖥️ SBC | Raspberry Pi Zero 2 W |
| 🎧 AI HAT | Whisplay AI HAT (ST7789 display + WM8960 audio) |
| 🔋 Battery | PiSugar 3 (1200 mAh, I²C management) |

> See [docs/HARDWARE.md](docs/HARDWARE.md) for the full pin-map and driver setup guide.

---

## 🚀 Quick Start

### 1 — Clone and install

```bash
git clone https://github.com/NaustudentX18/MiBud.git
cd MiBud
bash scripts/setup.sh        # installs system deps, venv, Python packages
```

### 2 — Configure (optional)

```bash
cp .env.example .env         # add your API keys if using cloud AI
# edit config/config.json    # or use the web wizard on first boot
```

### 3 — Start MiBud

```bash
bash scripts/run.sh          # launches the full app
# or run the web interface only:
source venv/bin/activate && python -m web.server
```

### 4 — Open the dashboard

Browse to **`http://mibud.local:5000`** (or your Pi's IP).  
First-time? The **Setup Wizard** walks you through every option in under 5 minutes.

### 5 — Validate your hardware

```bash
bash scripts/first_boot_check.sh
```

---

## 🆕 What's new in v2.0

MiBud just got a lot smarter on the same 512 MB of RAM:

- 🧠 **Long-term memory** — remembers your name, preferences, routines, and past
  conversations in a local SQLite store. Semantic recall is a single numpy
  matmul, so it's still fast on a Pi Zero 2 W. Auto-upgrades to Ollama
  `nomic-embed-text` when available; falls back to a zero-dep hashing embedder.
- 🛠️ **Tool use** — MiBud can now actually *do* things. Set timers, create
  reminders, take photos, describe what it sees, search the web, trigger Home
  Assistant, toggle GPIO, read its own battery — all via LLM function calls.
- 🗣️ **Streaming TTS** — first word leaves the speaker in under a second by
  splitting tokens into sentences and starting TTS before the model is done.
- 🔋 **Power profiles** — automatic ECO / BALANCED / PERFORMANCE switching
  based on battery and charge state. Brightness, poll rates, and LLM token
  budgets all follow.
- 🔔 **Proactive engine** — low-battery announcements, reminder/timer firing,
  morning greeting, idle check-ins — all respecting quiet hours and busy state.
- 🛡️ **Hardened AI router** — per-provider circuit breaker, exponential backoff
  retries, cached connectivity probe, moving-average latency metrics.
- 🌐 **Web API v2** — SSE streaming chat, memory inspection/wipe, tool
  invocation, power control, unified `/api/health`.

---

## ✨ Features

### 🤖 AI Companionship
- **20+ Unique Personalities** — Chef, Therapist, DJ, Teacher, Comedian and more
- **Custom Personality Creator** — build your own via the web UI
- **Dual AI Mode** — cloud + offline working in tandem
- **Multi-Provider Support** — OpenAI, Anthropic, Google, DeepSeek, OpenRouter, Ollama

### 🔒 Privacy First
- **100 % Offline Mode** — no internet required with Ollama
- **Local AI** — GGUF models via Ollama (Phi-3, TinyLlama, Mistral…)
- **No Data Collection** — your conversations stay on your device

### 🎤 Voice & Audio
- **Wake Word Detection** — "Hey MiBud" activation
- **Voice Activity Detection** — knows when you are speaking
- **Push-to-Talk** — physical button on the HAT
- **Multiple TTS Options** — OpenAI TTS, Piper (offline)

### 📺 Whisplay HAT
- **240×280 Display** — animations and UI themes
- **20+ Themes** — matched to the active personality
- **WM8960 Audio** — crystal-clear capture and playback
- **RGB LED** — status at a glance
- **GPIO Buttons** — short/long/hold actions

### 🔋 Battery & Power
- **PiSugar 3 Support** — 8+ h portable use
- **Smart Power Management** — auto sleep/wake
- **Battery Monitoring** — low-level warnings and LED indicators

### 🌐 Web Interface
- **Setup Wizard** — guided 8-step onboarding
- **Live Dashboard** — chat, settings, system monitoring
- **REST API** — integrate with anything

### 📷 Vision (Optional)
- **Camera Support** — Picamera2 (CSI) and USB cameras
- **Image Understanding** — ask about what the camera sees

---

## 📂 Project Structure

```
MiBud/
├── core/               # State machine, config, event bus
├── ai/                 # Multi-provider AI router, wake-word, TTS/STT
├── personalities/      # 20+ preset personalities + custom manager
├── hardware/           # Display, audio, buttons, battery, LED, camera
├── web/                # Flask server, setup wizard, dashboard templates
├── sync/               # Multi-device peer-to-peer sync
├── home/               # Home automation (GPIO + Home Assistant)
├── utils/              # Timers, reminders, notes
├── scripts/            # setup.sh · run.sh · first_boot_check.sh
├── deploy/             # mibud.service (systemd)
├── docs/               # HARDWARE.md · FIRST_BOOT_VALIDATION.md
├── tests/              # Unit and integration tests
├── .env.example        # Environment variable template
└── requirements.txt    # Python dependencies
```

---

## 🧠 AI Providers

### ☁️ Cloud (free tier available)
| Provider | Models |
|----------|--------|
| OpenRouter | Gemini, Llama, Mixtral *(free tier)* |
| OpenAI | GPT-4o with vision |
| Anthropic | Claude 3.5 Sonnet |
| Google | Gemini 2.0 Flash |
| DeepSeek | DeepSeek Chat |

### 🖥️ Offline (local)
| Provider | Models |
|----------|--------|
| Ollama | Phi-3, TinyLlama, Mistral, Qwen2 |

---

## 🔧 Configuration

Edit `config/config.json` (auto-created on first run):

```json
{
    "ai": {
        "default_provider": "openrouter",
        "model": "google/gemini-2.0-flash-lite:free"
    },
    "personality": {
        "current": "assistant"
    },
    "features": {
        "enable_wake_word": true,
        "enable_anomaly_detection": false,
        "enable_multi_device_sync": false
    }
}
```

Or set API keys via environment variables — copy `.env.example` to `.env`.

---

## 🌐 Web API (Quick Reference)

### v1 (stable)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | System state, battery, personality |
| `/api/config` | GET / POST | Read or update config |
| `/api/personality/list` | GET | All available personalities |
| `/api/personality/create` | POST | Create a custom personality |
| `/api/camera/capture` | GET | Capture image from camera |
| `/api/system/info` | GET | CPU, RAM, storage |
| `/api/alerts` | GET | Anomaly alert history |

### v2 (new in 2.0)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Unified subsystem health (no auth) |
| `/api/chat/stream` | POST | SSE streaming chat |
| `/api/memory/stats` | GET | Memory counters + session id |
| `/api/memory/facts` | GET | List durable facts |
| `/api/memory/search` | POST | Semantic recall across memory |
| `/api/memory/fact` | POST / DELETE | Add / delete fact |
| `/api/memory/profile` | GET / POST | Structured user profile |
| `/api/memory/sessions` | GET | Recent session summaries |
| `/api/memory/wipe` | POST | Nuke all memory (requires confirm) |
| `/api/tools/list` | GET | Registered tool schemas |
| `/api/tools/invoke` | POST | Call a tool directly |
| `/api/power/status` | GET | Current power profile |
| `/api/power/profile` | POST | Switch profile (auto / eco / balanced / performance) |
| `/api/providers/health` | GET | Circuit-breaker + latency metrics |

---

## 📊 Performance (Pi Zero 2 W)

| Metric | Target |
|--------|--------|
| Startup time | < 30 s |
| Voice response (cloud) | ~ 2.5 s |
| Voice response (Ollama) | ~ 4 s |
| Memory usage | ~ 180 MB |
| Battery life | 8–10 h |

---

## 🛠️ Development

```bash
# Setup
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Run tests
python -m pytest tests/ -v

# Lint
ruff check .

# Demo mode (no hardware needed)
python demo.py
```

---

## 🗺️ Roadmap

- [ ] Camera vision integration with cloud AI
- [ ] Advanced TTS — Piper offline voice cloning
- [ ] Wake-word model fine-tuning
- [ ] Community personality sharing
- [ ] Mobile companion app
- [ ] Hardened power-loss recovery
- [ ] Release packaging pipeline

---

## 📚 Documentation

| Doc | Description |
|-----|-------------|
| [docs/HARDWARE.md](docs/HARDWARE.md) | Pin map, driver setup, HAT wiring |
| [docs/FIRST_BOOT_VALIDATION.md](docs/FIRST_BOOT_VALIDATION.md) | Step-by-step boot validation |
| [CHANGELOG.md](CHANGELOG.md) | Version history |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute |

---

## 🤝 Contributing

Contributions are welcome — bugs, features, docs, new personalities, hardware tests.  
Please read [CONTRIBUTING.md](CONTRIBUTING.md) and follow our [Code of Conduct](CODE_OF_CONDUCT.md).

---

## 📜 License

[MIT License](LICENSE) — free to use, modify, and distribute.

---

<div align="center">

**Own it. Control it. Trust it. 🔒**

```
╔═══════════════════════════════════════╗
║         MiBud — AI Companion          ║
║   Privacy-First · Offline-First       ║
╚═══════════════════════════════════════╝
```

</div>
