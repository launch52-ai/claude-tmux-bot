#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
ENV_EXAMPLE="$SCRIPT_DIR/.env.example"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║     Claude Tmux Bot — Installation       ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# =============================================
#  1. System checks
# =============================================

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
echo "  ✓ Python $PYTHON_VERSION"

if command -v tmux &>/dev/null; then
    echo "  ✓ tmux $(tmux -V | cut -d' ' -f2)"
else
    echo "  ⚠ tmux not found — install before running the bot:"
    echo "    brew install tmux"
fi

# =============================================
#  2. Dependencies
# =============================================

echo ""
echo "Installing dependencies..."

if command -v brew &>/dev/null; then
    if ! brew list cairo &>/dev/null 2>&1; then
        echo "  Installing cairo via Homebrew..."
        brew install cairo
    fi
fi

pip3 install -q --no-warn-script-location -r "$SCRIPT_DIR/requirements.txt" 2>&1 | grep -v "^WARNING.*pip version"
echo "  ✓ Python packages installed"

# =============================================
#  3. Directories
# =============================================

mkdir -p ~/.ctb/media ~/.ctb/logs ~/.ctb/hooks ~/.ctb/hook_events
chmod 700 ~/.ctb ~/.ctb/media ~/.ctb/logs ~/.ctb/hooks ~/.ctb/hook_events

if [ ! -f "$ENV_FILE" ]; then
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
fi

# =============================================
#  4. Check if already configured
# =============================================

EXISTING_CHAT_ID=$(grep -E '^CTB_CHAT_ID=' "$ENV_FILE" 2>/dev/null | cut -d= -f2 || echo "")
if [ -n "$EXISTING_CHAT_ID" ] && [ "$EXISTING_CHAT_ID" != "" ] && [ "$EXISTING_CHAT_ID" != "-100XXXXXXXXXX" ]; then
    echo ""
    echo "  ✓ Already configured (chat ID: $EXISTING_CHAT_ID)"
    echo ""
    echo "  Run the bot:  python3 main.py"
    echo "  To reconfigure: delete .env and re-run this script."
    echo ""
    exit 0
fi

# =============================================
#  5. Create a Telegram bot
# =============================================

echo ""
echo "─────────────────────────────────────────────"
echo "  Step 1: Create a Telegram Bot"
echo "─────────────────────────────────────────────"
echo ""

EXISTING_TOKEN=$(grep -E '^CTB_BOT_TOKEN=' "$ENV_FILE" 2>/dev/null | cut -d= -f2 || echo "")

if [ -z "$EXISTING_TOKEN" ] || [ "$EXISTING_TOKEN" = "your-telegram-bot-token" ]; then
    echo "  Open Telegram and do the following:"
    echo ""
    echo "  1. Search for @BotFather and open a chat"
    echo "  2. Send:  /newbot"
    echo "  3. Choose a name (e.g., 'My Tmux Bot')"
    echo "  4. Choose a username (e.g., 'my_tmux_bot')"
    echo "  5. BotFather will reply with a token like:"
    echo "     123456789:ABCdefGHIjklMNOpqrSTUvwxYZ"
    echo ""
    read -rp "  Paste your bot token here: " BOT_TOKEN
    echo ""

    if [ -z "$BOT_TOKEN" ]; then
        echo "  No token provided. Edit .env manually later."
        exit 0
    fi
    # Use awk to avoid issues with special chars in token
    awk -v token="$BOT_TOKEN" '{
        if ($0 ~ /^CTB_BOT_TOKEN=/) print "CTB_BOT_TOKEN=" token;
        else print
    }' "$ENV_FILE" > "$ENV_FILE.tmp" && mv "$ENV_FILE.tmp" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
else
    BOT_TOKEN="$EXISTING_TOKEN"
    echo "  ✓ Bot token already in .env"
fi

# =============================================
#  6. Set up the Telegram group
# =============================================

echo "─────────────────────────────────────────────"
echo "  Step 2: Set Up the Telegram Group"
echo "─────────────────────────────────────────────"
echo ""
echo "  In Telegram, do the following:"
echo ""
echo "  1. Create a new group (or use an existing one)"
echo "     → Tap '+ New Group', add anyone, name it"
echo ""
echo "  2. Convert it to a supergroup with Topics:"
echo "     → Open group → tap group name → Edit"
echo "     → Scroll down → enable 'Topics'"
echo "     (If you don't see Topics, make sure"
echo "      the group has at least 1 other member)"
echo ""
echo "  3. Add your bot as admin:"
echo "     → Group settings → Administrators → Add Admin"
echo "     → Search for your bot's username"
echo "     → Grant 'Manage Topics' permission → Save"
echo ""
echo "  4. Send any message in the group"
echo "     (This is how the bot detects your group ID)"
echo ""

# =============================================
#  7. Auto-detect chat ID and user ID
# =============================================

while true; do
    read -rp "  Press Enter after you've done these steps (q to quit)... " RESPONSE
    if [ "$RESPONSE" = "q" ] || [ "$RESPONSE" = "Q" ]; then
        echo ""
        echo "  Setup incomplete. Finish later by re-running: ./install.sh"
        exit 0
    fi

    echo ""
    echo "  Listening for your message in Telegram (60s)..."
    echo ""

    if python3 "$SCRIPT_DIR/setup.py" "$BOT_TOKEN" "$ENV_FILE" 60; then
        echo ""
        echo "  ✓ Chat ID and User ID saved to .env"
        break
    else
        echo ""
        echo "  ✗ No message received. Please check:"
        echo "    • The bot is added to the group as admin"
        echo "    • You sent a message in the group (not a DM)"
        echo "    • The bot token is correct"
        echo ""
    fi
done

# =============================================
#  8. Optional configuration
# =============================================

echo ""
echo "─────────────────────────────────────────────"
echo "  Step 3: Configuration (optional)"
echo "─────────────────────────────────────────────"
echo ""

# Topic mode
echo "  Topic mode — how tmux maps to Telegram topics:"
echo "    1) session (default) — one topic per tmux session"
echo "    2) window — one topic per tmux window"
echo ""
read -rp "  Choose [1/2] (Enter for default): " TOPIC_MODE_CHOICE
if [ "$TOPIC_MODE_CHOICE" = "2" ]; then
    sed -i '' "s|^#\? *CTB_TOPIC_MODE=.*|CTB_TOPIC_MODE=window|" "$ENV_FILE"
    echo "  ✓ Topic mode: window"
else
    echo "  ✓ Topic mode: session"
fi

# Topic cleanup
echo ""
echo "  When a tmux session/window is killed, what should happen"
echo "  to its Telegram topic?"
echo "    1) Close the topic (default) — topic is archived but kept"
echo "    2) Delete the topic — permanently removed"
echo ""
read -rp "  Choose [1/2] (Enter for default): " CLEANUP_CHOICE
if [ "$CLEANUP_CHOICE" = "2" ]; then
    if grep -q "CTB_TOPIC_CLEANUP" "$ENV_FILE" 2>/dev/null; then
        sed -i '' "s|^#\? *CTB_TOPIC_CLEANUP=.*|CTB_TOPIC_CLEANUP=delete|" "$ENV_FILE"
    else
        echo "CTB_TOPIC_CLEANUP=delete" >> "$ENV_FILE"
    fi
    echo "  ✓ Topic cleanup: delete"
else
    echo "  ✓ Topic cleanup: close"
fi

# Sleep prevention
echo ""
echo "  Prevent Mac from sleeping while bot is running?"
echo "    1) Yes (default) — keeps Mac awake via caffeinate"
echo "    2) No"
echo ""
read -rp "  Choose [1/2] (Enter for default): " CAFFEINATE_CHOICE
if [ "$CAFFEINATE_CHOICE" = "2" ]; then
    sed -i '' "s|^#\? *CTB_CAFFEINATE=.*|CTB_CAFFEINATE=false|" "$ENV_FILE"
    echo "  ✓ Caffeinate: off"
else
    echo "  ✓ Caffeinate: on"
fi

# =============================================
#  Done
# =============================================

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║         ✓ Setup Complete!                ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Ensure at least one tmux session exists
if command -v tmux &>/dev/null; then
    if ! tmux list-sessions &>/dev/null 2>&1; then
        echo "  Creating default tmux session 'main'..."
        tmux new-session -d -s main
        echo "  ✓ Created tmux session 'main'"
        echo ""
    fi
fi

echo "  What would you like to do?"
echo ""
echo "    1) Start the bot now"
echo "    2) Install as a service (starts now, auto-restarts on login)"
echo "    3) Exit (start manually later with: python3 main.py)"
echo ""
read -rp "  Choose [1/2/3]: " POST_CHOICE

case "$POST_CHOICE" in
    1)
        echo ""
        echo "  Starting the bot..."
        echo ""
        exec python3 "$SCRIPT_DIR/main.py"
        ;;
    2)
        echo ""
        echo "  Installing as a launchd service..."
        cd "$SCRIPT_DIR"
        SERVICE_RESULT=$(python3 -c "import service; print(service.install())" 2>&1)
        if echo "$SERVICE_RESULT" | grep -q "^Error"; then
            echo "  ⚠ $SERVICE_RESULT"
            echo ""
            echo "  Start manually instead:  python3 main.py"
            echo "  Or install later from Telegram: /service install"
        else
            echo "  ✓ $SERVICE_RESULT"
            echo "  Bot files deployed to ~/.ctb/app/"
            echo ""
            echo "  Manage from Telegram: /service status | /service uninstall"
            echo ""
            read -rp "  Remove this project directory ($SCRIPT_DIR)? [y/N]: " REMOVE_DIR
            if [ "$REMOVE_DIR" = "y" ] || [ "$REMOVE_DIR" = "Y" ]; then
                rm -rf "$SCRIPT_DIR"
                echo "  ✓ Project directory removed"
            else
                echo "  · Kept project directory"
            fi
        fi
        echo ""
        ;;
    *)
        echo ""
        echo "  To start the bot later:"
        echo "    python3 main.py"
        echo ""
        echo "  To install as a service (from Telegram):"
        echo "    Send /service install in the Control topic"
        echo ""
        ;;
esac
