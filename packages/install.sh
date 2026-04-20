#!/usr/bin/env bash
# ------------------------------------------------------------
# MiBud bundle installer
# ------------------------------------------------------------
# Extracts the bundle (if not already), creates a venv, installs
# dependencies in the right order, wires up the systemd service,
# and prints next steps.
#
# Usage (on the Pi):
#     tar xzf mibud-3.0.0-bundle.tar.gz
#     cd mibud-3.0.0
#     sudo ./install.sh
#
# Flags:
#     --no-service   skip installing/enabling the systemd unit
#     --no-hardware  skip the [pi] hardware extra (laptop install)
# ------------------------------------------------------------
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/home/pi/MiBud}"
SERVICE_USER="${SERVICE_USER:-pi}"
INSTALL_SERVICE=1
INSTALL_HARDWARE=1

for arg in "$@"; do
    case "$arg" in
        --no-service)  INSTALL_SERVICE=0 ;;
        --no-hardware) INSTALL_HARDWARE=0 ;;
        -h|--help)
            sed -n '2,20p' "$0"
            exit 0
            ;;
    esac
done

BUNDLE_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "╔══════════════════════════════════════════════════════════╗"
echo "║                MiBud Bundle Installer                    ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo "Source    : $BUNDLE_DIR"
echo "Target    : $INSTALL_DIR"
echo "User      : $SERVICE_USER"
echo "Service   : $([ $INSTALL_SERVICE = 1 ] && echo yes || echo skip)"
echo "Hardware  : $([ $INSTALL_HARDWARE = 1 ] && echo yes || echo skip)"
echo ""

# --- Python version gate --------------------------------------------------
python3 -c "import sys; assert sys.version_info >= (3, 10)" 2>/dev/null || {
    echo "✖ Python 3.10+ required. Found: $(python3 --version 2>&1)"
    exit 1
}
echo "✔ Python $(python3 -c 'import sys; print(*sys.version_info[:2], sep=\".\")')"

# --- System packages (Pi only) --------------------------------------------
if [ "$INSTALL_HARDWARE" = 1 ] && [ -f /etc/debian_version ]; then
    echo ""
    echo "📦 Installing apt dependencies (sudo)…"
    sudo apt-get update -qq
    sudo apt-get install -y \
        python3-pip python3-dev python3-venv \
        libasound2-dev portaudio19-dev \
        libusb-1.0-0-dev libhidapi-libusb0 libgpiod-dev \
        libopenblas-dev libatlas-base-dev liblapack-dev \
        libfreetype6-dev libjpeg-dev zlib1g-dev
fi

# --- Copy source ----------------------------------------------------------
if [ "$BUNDLE_DIR" != "$INSTALL_DIR" ]; then
    echo ""
    echo "📁 Staging source to $INSTALL_DIR"
    sudo mkdir -p "$INSTALL_DIR"
    sudo cp -a "$BUNDLE_DIR"/. "$INSTALL_DIR"/
    sudo chown -R "$SERVICE_USER":"$SERVICE_USER" "$INSTALL_DIR" 2>/dev/null || true
fi
cd "$INSTALL_DIR"

# --- Virtualenv -----------------------------------------------------------
echo ""
echo "🐍 Creating virtualenv at $INSTALL_DIR/venv"
if [ ! -d venv ]; then
    python3 -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate
pip install --quiet --upgrade pip wheel

# --- Install wheel --------------------------------------------------------
WHEEL="$(ls "$BUNDLE_DIR"/mibud-*-py3-none-any.whl 2>/dev/null | head -1)"
if [ -z "$WHEEL" ]; then
    echo "✖ No wheel found in bundle."
    exit 1
fi
echo ""
echo "📦 Installing $WHEEL"
if [ "$INSTALL_HARDWARE" = 1 ]; then
    pip install --quiet "$WHEEL[cloud,offline,vad,pi]" || {
        echo "⚠ Hardware extras failed. Retrying without [pi]…"
        pip install --quiet "$WHEEL[cloud,offline,vad]"
    }
else
    pip install --quiet "$WHEEL[cloud,offline,vad]"
fi

# --- Runtime dirs ---------------------------------------------------------
mkdir -p config/profiles models logs data plugins

# --- .env stub ------------------------------------------------------------
if [ ! -f .env ]; then
    cat > .env <<'EOF'
# MiBud API keys — fill in what you need.
# OPENAI_API_KEY=
# ANTHROPIC_API_KEY=
# GOOGLE_API_KEY=
# OPENROUTER_API_KEY=
# DEEPSEEK_API_KEY=
EOF
    echo "ℹ  Created .env template — edit to add your keys."
fi

# --- systemd --------------------------------------------------------------
if [ "$INSTALL_SERVICE" = 1 ] && [ -f deploy/mibud.service ]; then
    echo ""
    echo "🔧 Installing systemd service…"
    sudo install -m 644 deploy/mibud.service /etc/systemd/system/mibud.service
    sudo systemctl daemon-reload
    sudo systemctl enable mibud.service
    echo "   → sudo systemctl start mibud     to launch now"
    echo "   → journalctl -u mibud -f         to follow logs"
fi

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║                   ✅ Install complete                    ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo "Run interactively:  source venv/bin/activate && mibud"
echo "Web dashboard:      http://mibud.local:5000"
