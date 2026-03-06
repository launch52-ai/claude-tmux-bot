#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
ENV_EXAMPLE="$SCRIPT_DIR/.env.example"

echo "=== Claude Tmux Bot — Install ==="
echo ""

# --- Check Python version ---
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Please install Python 3.9+."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PYTHON_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')

if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 9 ]; }; then
    echo "ERROR: Python 3.9+ required, found $PYTHON_VERSION"
    exit 1
fi
echo "Python $PYTHON_VERSION"

# --- Check tmux ---
if command -v tmux &>/dev/null; then
    echo "tmux $(tmux -V | cut -d' ' -f2)"
else
    echo "WARNING: tmux not found. Install it before running the bot."
    echo "  brew install tmux"
fi

# --- Install cairo (required by cairosvg for SVG→PNG screenshots) ---
if command -v brew &>/dev/null; then
    if ! brew list cairo &>/dev/null 2>&1; then
        echo ""
        echo "Installing cairo via Homebrew..."
        brew install cairo
    else
        echo "cairo installed"
    fi
else
    echo "WARNING: Homebrew not found. Install cairo manually for screenshot support."
fi

# --- Python dependencies ---
echo ""
echo "Installing Python dependencies..."
pip3 install -r "$SCRIPT_DIR/requirements.txt"

# --- Create data directories ---
mkdir -p ~/.ctb/media
mkdir -p ~/.ctb/logs
mkdir -p ~/.ctb/hooks
mkdir -p ~/.ctb/hook_events

# --- Setup .env file ---
echo ""
if [ -f "$ENV_FILE" ]; then
    echo ".env file already exists — skipping."
else
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    echo "Created .env from .env.example"
    echo ""

    # Prompt for required values
    read -rp "Telegram bot token (from @BotFather): " BOT_TOKEN
    read -rp "Forum supergroup chat ID (negative number): " CHAT_ID
    read -rp "Your Telegram user ID: " USER_ID

    if [ -n "$BOT_TOKEN" ]; then
        sed -i '' "s|CTB_BOT_TOKEN=.*|CTB_BOT_TOKEN=$BOT_TOKEN|" "$ENV_FILE"
    fi
    if [ -n "$CHAT_ID" ]; then
        sed -i '' "s|CTB_CHAT_ID=.*|CTB_CHAT_ID=$CHAT_ID|" "$ENV_FILE"
    fi
    if [ -n "$USER_ID" ]; then
        sed -i '' "s|CTB_ALLOWED_USER_ID=.*|CTB_ALLOWED_USER_ID=$USER_ID|" "$ENV_FILE"
    fi

    echo ""
    echo "Saved to .env — edit it later if needed: $ENV_FILE"
fi

# --- Done ---
echo ""
echo "=== Install complete ==="
echo ""
echo "Next steps:"
if ! command -v tmux &>/dev/null; then
    echo "  1. Install tmux: brew install tmux"
    echo "  2. Start a tmux session: tmux new-session -d -s main"
    echo "  3. Run the bot: python3 main.py"
else
    echo "  1. Start a tmux session (if none running): tmux new-session -d -s main"
    echo "  2. Run the bot: python3 main.py"
fi
echo "  Optional: install as a service from Telegram with /service install"
