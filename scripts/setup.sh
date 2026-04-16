#!/bin/bash
# MiBud Setup Script
# Privacy-Focused AI Companion for Raspberry Pi Zero 2 W + WhisPlay HAT + PiSugar 3

set -e

echo "╔══════════════════════════════════════════════════════════╗"
echo "║           MiBud Setup - AI Companion Setup              ║"
echo "║   Privacy-Focused | Offline-First | Custom Personalities  ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# ── Python Version Check ──────────────────────────────────────
python3 -c "import sys; assert sys.version_info >= (3, 10)" 2>/dev/null || {
    echo "❌ Python 3.10+ required. Current: $(python3 --version 2>&1)"
    exit 1
}
echo "✅ Python $(python3 -c 'import sys; print(*sys.version_info[:2], sep=".")')"

# ── System Update ──────────────────────────────────────────────
echo ""
echo "📦 Updating system packages..."
sudo apt-get update -qq
sudo apt-get upgrade -y -qq

# ── Core Dependencies ──────────────────────────────────────────
echo ""
echo "📥 Installing system dependencies..."
sudo apt-get install -y \
    python3-pip \
    python3-dev \
    python3-venv \
    git \
    curl \
    wget \
    vim \
    htop \
    i2c-tools \
    spi-tools \
    libasound2-dev \
    portaudio19-dev \
    libusb-1.0-0-dev \
    libhidapi-libusb0 \
    libgpiod-dev \
    libopenblas-dev \
    libatlas-base-dev \
    liblapack-dev \
    libfreetype6-dev \
    libjpeg-dev \
    zlib1g-dev

# ── Enable Hardware Interfaces ──────────────────────────────────
echo ""
echo "⚙️  Enabling SPI and I2C..."
sudo raspi-config nonint do_spi 0
sudo raspi-config nonint do_i2c 0

# ── WhisPlay HAT Driver ────────────────────────────────────────
echo ""
echo "🔊 Installing WhisPlay HAT driver..."
WHISPLAY_DIR="/home/pi/Whisplay"

if [ ! -d "$WHISPLAY_DIR" ]; then
    cd /home/pi
    git clone https://github.com/PiSugar/Whisplay.git --depth 1
    cd Whisplay/Driver
    sudo bash install_wm8960_driver.sh 2>/dev/null || true
    cd /home/pi
else
    echo "   WhisPlay driver already installed"
fi

# ── Fonts for Display ─────────────────────────────────────────
echo ""
echo "🔤 Installing fonts..."
sudo apt-get install -y fonts-dejavu-core fonts-noto-color-emoji

# ── Python Virtual Environment ──────────────────────────────────
echo ""
echo "🐍 Setting up Python virtual environment..."
cd /home/pi/MiBud

if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

source venv/bin/activate
pip install --upgrade pip

# ── Install Python Dependencies ────────────────────────────────
echo ""
echo "📦 Installing Python dependencies..."
pip install -r requirements.txt

# ── Create Directories ─────────────────────────────────────────
echo ""
echo "📁 Creating directories..."
mkdir -p config/profiles
mkdir -p models
mkdir -p logs
mkdir -p data

# ── Download Ollama (Offline AI) ──────────────────────────────
echo ""
echo "🧠 Setting up Ollama for offline AI..."
if ! command -v ollama &> /dev/null; then
    curl -fsSL https://ollama.ai/install.sh | sh
else
    echo "   Ollama already installed"
fi

# ── Download Local AI Models ──────────────────────────────────
echo ""
echo "📥 Downloading offline AI models (this may take a while)..."
ollama pull phi3:latest
ollama pull tinyllama:latest
ollama pull mistral:latest

# ── Create .env from example ──────────────────────────────────
echo ""
echo "🔑 Creating .env file for API keys..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "   Created .env — add your API keys there"
else
    echo "   .env already exists"
fi

# ── Create Config File ─────────────────────────────────────────
echo ""
echo "⚙️  Creating configuration..."
cat > config/config.json << 'EOF'
{
    "config_version": 1,
    "ai": {
        "default_provider": "openrouter",
        "offline_provider": "ollama",
        "stt_provider": "whisper_api",
        "tts_provider": "openai_tts",
        "model": "google/gemini-2.0-flash-lite:free",
        "offline_model": "phi3:latest",
        "ollama_url": "http://localhost:11434"
    },
    "personality": {
        "current": "assistant",
        "voice_speed": 1.0,
        "voice_pitch": 1.0,
        "voice_style": "neutral"
    },
    "wake_word": {
        "enabled": true,
        "words": ["hey mibud", "ok pi", "hey assistant"],
        "sensitivity": 0.5,
        "use_button": true
    },
    "hardware": {
        "display_brightness": 70,
        "display_rotation": 0,
        "audio_input_device": "plughw:1,0",
        "audio_output_device": "default",
        "audio_sample_rate": 16000,
        "enable_led": true
    },
    "display": {
        "theme": "auto",
        "show_clock": true,
        "show_battery": true,
        "show_wifi": true,
        "idle_timeout": 60,
        "sleep_timeout": 300
    },
    "network": {
        "hostname": "mibud",
        "auto_reconnect": true
    },
    "features": {
        "enable_tts": true,
        "enable_stt": true,
        "enable_weather": true,
        "enable_timers": true,
        "enable_home_assistant": false,
        "enable_speaker_recognition": false,
        "enable_anomaly_detection": false,
        "enable_multi_device_sync": false
    },
    "tuning": {
        "conversation_max_history": 10,
        "stt_silence_threshold": 500,
        "stt_max_silence_chunks": 30,
        "vad_threshold": 200,
        "vad_min_trigger_frames": 3,
        "vad_cooldown_seconds": 2.0,
        "battery_low_threshold": 20,
        "battery_critical_threshold": 5,
        "sync_interval_seconds": 30,
        "ai_max_tokens": 500,
        "idle_timeout_seconds": 60,
        "sleep_timeout_seconds": 300
    },
    "first_run": true,
    "setup_complete": false
}
EOF

# ── Create Service File ─────────────────────────────────────────
echo ""
echo "🔧 Creating systemd service..."
sudo tee /etc/systemd/system/mibud.service > /dev/null << 'EOF'
[Unit]
Description=MiBud AI Companion
After=network.target ollama.service

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/MiBud
ExecStart=/home/pi/MiBud/venv/bin/python -m core.main
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Enable service
sudo systemctl daemon-reload
sudo systemctl enable mibud

# ── Final Message ──────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║               ✅ MiBud Setup Complete!                   ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "🚀 To start MiBud:"
echo "   cd /home/pi/MiBud"
echo "   source venv/bin/activate"
echo "   python -m core.main"
echo ""
echo "📋 Or run as service:"
echo "   sudo systemctl start mibud"
echo "   sudo systemctl status mibud"
echo ""
echo "🌐 Access web interface at:"
echo "   http://mibud.local:5000"
echo ""
echo "🔧 To configure API keys:"
echo "   nano config/config.json"
echo "   # Then add your API keys"
echo ""
echo "📖 For first-time setup, the wizard will guide you!"
echo ""
