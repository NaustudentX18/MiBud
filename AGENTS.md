# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

MiBud is a privacy-focused AI companion for Raspberry Pi Zero 2 W. The codebase is a Python 3.10+ application with Flask web dashboard, multi-provider AI routing, and hardware drivers. The actual source lives on the `develop` branch (merged into the working branch).

### Running the application

- **Web server (dev):** `source venv/bin/activate && python -m web.server` — starts Flask on port 5000
- **Full app:** `source venv/bin/activate && python -m core.main` — starts the full MiBud app (will use mock hardware on non-Pi)
- **Demo mode:** `source venv/bin/activate && python demo.py` — interactive demo without hardware

### Testing and linting

- **Tests:** `source venv/bin/activate && python -m pytest tests/ -v` (2 of 12 tests fail due to a pre-existing bug: `StateManager` lacks a `get_state()` method called by tests)
- **Lint:** `source venv/bin/activate && ruff check .` (75 pre-existing lint warnings; the linter runs correctly)

### Key gotchas

- Several `requirements.txt` packages are Raspberry Pi-specific (`RPi.GPIO`, `spidev`, `smbus2`, `picamera2`, `pyalsaaudio`, `piper-tts`) and will not install on x86. Install only the platform-compatible subset (see update script).
- `config/config.json` must exist with `"setup_complete": true` and `"first_run": false` to skip the first-run wizard and go directly to normal mode. The update script creates this if needed.
- Directories `config/profiles`, `models`, `logs`, `data` must exist at the project root.
- The web server is a standalone Flask app (`web/server.py`) that can be started independently of the full `core.main` entry point, which is useful for testing web routes without hardware dependencies.
- AI features require at least one configured API key or a running Ollama instance. Without these, the app still starts but AI chat will return "no providers available."
