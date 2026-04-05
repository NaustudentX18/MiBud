#!/usr/bin/env bash
# MiBud First Boot Check
# Run from the project root: bash scripts/first_boot_check.sh

set -euo pipefail

PASS=0
FAIL=0
WARN=0

pass()  { echo "  ✅ $*"; PASS=$((PASS + 1)); }
fail()  { echo "  ❌ $*"; FAIL=$((FAIL + 1)); }
warn()  { echo "  ⚠️  $*"; WARN=$((WARN + 1)); }
header(){ echo ""; echo "── $* ──────────────────────────────────────"; }

echo "╔══════════════════════════════════════╗"
echo "║   MiBud First Boot Validation        ║"
echo "╚══════════════════════════════════════╝"

# ── Python ────────────────────────────────────────────────────
header "Python"
if python3 -c "import sys; assert sys.version_info >= (3, 10)" 2>/dev/null; then
    pass "Python 3.10+ available"
else
    fail "Python 3.10+ required"
fi

if [ -d "venv" ]; then
    pass "Virtual environment found"
else
    warn "venv not found — run: bash scripts/setup.sh"
fi

# ── Core Imports ──────────────────────────────────────────────
header "Core imports"
VENV_PYTHON="python3"
[ -f "venv/bin/python" ] && VENV_PYTHON="venv/bin/python"

if $VENV_PYTHON -c "from core.config import Config; Config()" 2>/dev/null; then
    pass "core.config imports OK"
else
    fail "core.config import failed"
fi

if $VENV_PYTHON -c "from core.state import StateManager" 2>/dev/null; then
    pass "core.state imports OK"
else
    fail "core.state import failed"
fi

if $VENV_PYTHON -c "from personalities.presets import get_all_personalities; p = get_all_personalities(); assert len(p) >= 10" 2>/dev/null; then
    pass "personalities loaded ($(  $VENV_PYTHON -c "from personalities.presets import get_all_personalities; print(len(get_all_personalities()))" 2>/dev/null || echo '?') presets)"
else
    fail "personalities import failed"
fi

# ── Configuration ─────────────────────────────────────────────
header "Configuration"
if [ -f "config/config.json" ]; then
    if python3 -c "import json; json.load(open('config/config.json'))" 2>/dev/null; then
        pass "config/config.json is valid JSON"
    else
        fail "config/config.json is invalid JSON"
    fi
else
    warn "config/config.json missing — first-run wizard will appear on next start"
fi

# ── Required Directories ───────────────────────────────────────
header "Directories"
for dir in config logs data; do
    if [ -d "$dir" ]; then
        pass "$dir/ exists"
    else
        mkdir -p "$dir"
        warn "$dir/ created (was missing)"
    fi
done

# ── Raspberry Pi Hardware ─────────────────────────────────────
header "Hardware (Pi only)"
if [ -f /proc/device-tree/model ] && grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
    pass "Raspberry Pi detected: $(cat /proc/device-tree/model)"

    # I²C
    if command -v i2cdetect &>/dev/null; then
        I2C_DEVICES=$(i2cdetect -y 1 2>/dev/null | grep -oP '[0-9a-f]{2}(?=:)' || true)
        if echo "$I2C_DEVICES" | grep -q "1a"; then
            pass "WM8960 audio codec found (0x1a)"
        else
            warn "WM8960 not detected on I²C bus (check HAT connection)"
        fi
        if echo "$I2C_DEVICES" | grep -q "57"; then
            pass "PiSugar 3 battery found (0x57)"
        else
            warn "PiSugar 3 not detected (check connection)"
        fi
    else
        warn "i2cdetect not available — skipping hardware scan"
    fi

    # SPI
    if ls /dev/spidev* &>/dev/null; then
        pass "SPI device(s) present: $(ls /dev/spidev* | tr '\n' ' ')"
    else
        warn "No SPI device — display may not work (enable SPI in raspi-config)"
    fi

    # Audio
    if aplay -l 2>/dev/null | grep -q "card"; then
        pass "Audio output device found"
    else
        warn "No audio output device found"
    fi
else
    warn "Not running on Raspberry Pi — hardware checks skipped"
fi

# ── Web Interface ─────────────────────────────────────────────
header "Web interface"
if $VENV_PYTHON -c "import flask; import web.server" 2>/dev/null; then
    pass "web.server imports OK"
else
    warn "web.server import failed (Flask may not be installed)"
fi

# ── Summary ───────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════"
echo "  Results: ✅ $PASS passed  ⚠️  $WARN warnings  ❌ $FAIL failed"
echo "══════════════════════════════════════════"
if [ "$FAIL" -eq 0 ]; then
    echo "  🚀 MiBud is ready for launch!"
else
    echo "  🔧 Fix the failed checks above before deploying."
    exit 1
fi
