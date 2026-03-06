#!/usr/bin/env bash
set -euo pipefail

echo "=== Claude Tmux Bot — Install ==="

# Install cairo (required by cairosvg for SVG→PNG rendering)
if command -v brew &>/dev/null; then
    if ! brew list cairo &>/dev/null 2>&1; then
        echo "Installing cairo via Homebrew..."
        brew install cairo
    else
        echo "cairo already installed."
    fi
else
    echo "WARNING: Homebrew not found. Please install cairo manually."
fi

# Python dependencies
echo "Installing Python dependencies..."
pip3 install -r "$(dirname "$0")/requirements.txt"

# Create data directories
mkdir -p ~/.ctb/media

echo "=== Install complete ==="
