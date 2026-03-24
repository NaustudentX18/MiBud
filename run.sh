#!/bin/bash
# MiBud Run Script

set -e

echo "🤖 Starting MiBud..."

# Check if running on Raspberry Pi
if [ -f /proc/device-tree/model ]; then
    MODEL=$(cat /proc/device-tree/model)
    if [[ $MODEL == *"Raspberry Pi"* ]]; then
        echo "📟 Raspberry Pi detected: $MODEL"
    fi
fi

# Activate virtual environment if exists
if [ -d "venv" ]; then
    echo "📦 Activating virtual environment..."
    source venv/bin/activate
fi

# Set environment variables
export MIBUD_CONFIG_DIR="${MIBUD_CONFIG_DIR:-config}"

# Create config directory if not exists
mkdir -p "$MIBUD_CONFIG_DIR"

# Run MiBud
echo "🚀 Launching MiBud..."
python -m core.main
