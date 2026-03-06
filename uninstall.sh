#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║    Claude Tmux Bot — Uninstall           ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# =============================================
#  1. Uninstall launchd service
# =============================================

PLIST="$HOME/Library/LaunchAgents/com.ctb.plist"
if [ -f "$PLIST" ]; then
    echo "  Stopping and removing launchd service..."
    launchctl unload "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "  ✓ Service removed"
else
    echo "  · No launchd service found"
fi

# =============================================
#  2. Remove Claude Code hooks
# =============================================

CLAUDE_SETTINGS="$HOME/.claude/settings.json"
HOOK_SCRIPT="$HOME/.ctb/hooks/ctb_hook.sh"

if [ -f "$CLAUDE_SETTINGS" ] && command -v python3 &>/dev/null; then
    echo "  Removing hooks from Claude Code settings..."
    cd "$SCRIPT_DIR"
    python3 -c "from claude.hooks import uninstall_hooks; uninstall_hooks()" 2>/dev/null && \
        echo "  ✓ Hooks removed from $CLAUDE_SETTINGS" || \
        echo "  ⚠ Could not remove hooks (edit $CLAUDE_SETTINGS manually)"
else
    echo "  · No Claude settings found"
fi

# =============================================
#  3. Remove ~/.ctb directory
# =============================================

CTB_DIR="$HOME/.ctb"
if [ -d "$CTB_DIR" ]; then
    echo ""
    echo "  The ~/.ctb directory contains:"
    echo "    - Hook scripts and event files"
    echo "    - Bot state (state.json)"
    echo "    - Logs"
    echo "    - Downloaded media files"
    echo ""
    read -rp "  Delete ~/.ctb and all its contents? [y/N]: " DELETE_CTB
    if [ "$DELETE_CTB" = "y" ] || [ "$DELETE_CTB" = "Y" ]; then
        rm -rf "$CTB_DIR"
        echo "  ✓ ~/.ctb removed"
    else
        echo "  · Kept ~/.ctb"
    fi
else
    echo "  · No ~/.ctb directory found"
fi

# =============================================
#  4. Remove .env file
# =============================================

ENV_FILE="$SCRIPT_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    echo ""
    read -rp "  Delete .env (contains bot token and chat ID)? [y/N]: " DELETE_ENV
    if [ "$DELETE_ENV" = "y" ] || [ "$DELETE_ENV" = "Y" ]; then
        rm -f "$ENV_FILE"
        echo "  ✓ .env removed"
    else
        echo "  · Kept .env"
    fi
fi

# =============================================
#  5. Uninstall Python packages (optional)
# =============================================

echo ""
read -rp "  Uninstall Python packages (aiogram, libtmux, etc.)? [y/N]: " UNINSTALL_PKGS
if [ "$UNINSTALL_PKGS" = "y" ] || [ "$UNINSTALL_PKGS" = "Y" ]; then
    pip3 uninstall -y -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null || true
    echo "  ✓ Python packages uninstalled"
else
    echo "  · Kept Python packages"
fi

# =============================================
#  Done
# =============================================

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║         ✓ Uninstall Complete             ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "  The project directory itself was not removed."
echo "  To fully remove: rm -rf $SCRIPT_DIR"
echo ""
