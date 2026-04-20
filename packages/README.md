# MiBud — Distribution Packages

Pre-built artifacts for **MiBud v3.0.0 "Aware"**, the privacy-focused AI
companion for the Raspberry Pi Zero 2 W.

| File                              | Size  | What it is                                                           |
| --------------------------------- | ----- | -------------------------------------------------------------------- |
| `mibud-3.0.0-py3-none-any.whl`    | ~145K | Python wheel — `pip install` for laptops or any existing Pi.         |
| `mibud-3.0.0.tar.gz`              | ~170K | Source distribution — same code as the wheel, plus tests and docs.   |
| `mibud-3.0.0-bundle.tar.gz`       | ~325K | **Pi-ready bundle** — source + wheel + `install.sh` for fresh Pis.   |
| `install.sh`                      | ~5K   | The standalone installer (already inside the bundle).                |

All three artifacts pin to the same commit and are reproducible from the
repo root with `python -m build --outdir packages/`.

---

## Pick your install path

### 1. Fresh Raspberry Pi Zero 2 W (recommended)

```bash
# On the Pi
wget https://github.com/NaustudentX18/MiBud/releases/download/v3.0.0/mibud-3.0.0-bundle.tar.gz
tar xzf mibud-3.0.0-bundle.tar.gz
cd mibud-3.0.0
sudo ./install.sh
```

`install.sh` will:

1. apt-install audio/GPIO/build deps (`portaudio19-dev`, `libasound2-dev`,
   `libgpiod-dev`, …).
2. Stage the source to `/home/pi/MiBud`.
3. Create a venv and `pip install` the wheel with the `cloud,offline,vad,pi`
   extras.
4. Drop a `.env` template if none exists.
5. Install and enable the `mibud.service` systemd unit.

After a reboot, the assistant is reachable at `http://mibud.local:5000`.

Flags:

| Flag             | Effect                                                       |
| ---------------- | ------------------------------------------------------------ |
| `--no-service`   | Skip systemd. Use when running interactively or in a sandbox.|
| `--no-hardware`  | Skip the `[pi]` extra (RPi.GPIO, picamera2, pyaudio, …).     |

Override paths via env vars:

```bash
INSTALL_DIR=/opt/mibud SERVICE_USER=mibud sudo ./install.sh
```

### 2. Laptop / dev machine (no hardware)

```bash
pip install mibud-3.0.0-py3-none-any.whl[cloud,offline,vad]
```

Then run with `mibud` (or `python -m core.main`). Hardware modules
gracefully degrade to mock implementations when their drivers are absent.

### 3. From source

```bash
pip install mibud-3.0.0.tar.gz[full,dev]
pytest                       # 154 tests, ~2 s
```

---

## Extras at a glance

| Extra      | Adds                                                           | When to install                          |
| ---------- | -------------------------------------------------------------- | ---------------------------------------- |
| `cloud`    | `openai`, `anthropic`, `google-generativeai`                   | Any cloud LLM provider                   |
| `offline`  | `ollama`, `llama-cpp-python`, `faster-whisper`, `vosk`         | Local-only operation                     |
| `vad`      | `onnxruntime` (for Silero VAD)                                 | Wanting the higher-precision VAD path    |
| `pi`       | `pyaudio`, `pyalsaaudio`, `RPi.GPIO`, `picamera2`, `piper-tts` | Real Pi target only                      |
| `full`     | `cloud + offline + vad`                                        | Convenience for laptop installs          |
| `dev`      | `pytest`, `pytest-asyncio`, `ruff`, `build`                    | Running tests / building releases        |

---

## Verifying a release

```bash
sha256sum packages/*.whl packages/*.tar.gz packages/*-bundle.tar.gz
```

The wheel ships every Python module under `ai/`, `core/`, `web/`,
`hardware/`, `personalities/`, `home/`, `sync/`, `utils/`, plus the web
templates and the `mibud.service` unit (under `share/mibud/` in the venv).

---

## Rebuilding

From the repo root:

```bash
pip install build
python -m build --outdir packages/

# Then re-make the bundle:
WORK=$(mktemp -d) && tar xzf packages/mibud-3.0.0.tar.gz -C $WORK && \
  cp packages/mibud-3.0.0-py3-none-any.whl packages/install.sh $WORK/mibud-3.0.0/ && \
  chmod +x $WORK/mibud-3.0.0/install.sh && \
  tar czf packages/mibud-3.0.0-bundle.tar.gz -C $WORK mibud-3.0.0 && \
  rm -rf $WORK
```
