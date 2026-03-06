# Claude Tmux Bot

A Python Telegram bot that provides full remote control of tmux sessions from your phone, primarily designed for interacting with Claude Code remotely.

The bot maps Telegram forum topics to tmux sessions (or windows) and uses inline keyboards for navigating windows/panes. It leverages Claude Code's hook system and JSONL transcript reading for Claude-specific panes, and terminal capture for generic panes. Prompts, tool results, and status events are rendered as native Telegram UI elements.

## Features

- **Forum Topic Mapping** — Each tmux session (or window) gets its own Telegram forum topic with live output streaming
- **Dual Data Source** — Claude Code hooks + JSONL transcripts for structured events; terminal capture as fallback for generic panes
- **Interactive Prompts** — Permission requests, bash approvals, multi-select questions, and plan reviews rendered as tappable inline keyboards
- **Persistent Action Bar** — Always-visible control buttons (Stop, Escape, Ctrl+C, Screenshot) that adapt to Claude's state
- **Voice Messages** — Send voice messages that get transcribed via Whisper and forwarded to Claude
- **Photo & File Transfer** — Send images/files from Telegram to your Mac (and vice versa)
- **Terminal Screenshots** — Render full ANSI-colored terminal output as PNG images via Rich + CairoSVG
- **Session Management** — Create, kill, split, and navigate sessions/windows/panes from Telegram
- **Directory Browser** — Paginated folder picker when creating new sessions
- **Sleep Prevention** — Built-in caffeinate control so your Mac stays awake during long tasks
- **launchd Service** — Install as a macOS service that auto-starts on login and survives reboots
- **Auto-Sync** — On startup, discovers all tmux sessions, creates topics, installs hooks, and resumes watching

## Tech Stack

- **Python 3.12+** with asyncio
- **aiogram 3.x** — async Telegram bot with forum topic support
- **libtmux** — Python tmux API
- **pydantic-settings** — configuration from env vars
- **rich** + **cairosvg** — terminal output to PNG rendering
- **openai** — Whisper API for voice transcription

## Quick Start

```bash
# Clone the repo
git clone https://github.com/launch52-ai/claude-tmux-bot.git
cd claude-tmux-bot

# Install dependencies
./install.sh

# Configure environment variables
export CTB_BOT_TOKEN="your-telegram-bot-token"
export CTB_CHAT_ID="your-forum-supergroup-chat-id"
export CTB_ALLOWED_USER_ID="your-telegram-user-id"

# Run
python main.py
```

### Prerequisites

1. A Telegram supergroup with **forum topics enabled**
2. A bot added as admin with `can_manage_topics` permission
3. tmux installed and running
4. Python 3.12+

## Configuration

| Variable | Description | Default |
|---|---|---|
| `CTB_BOT_TOKEN` | Telegram bot token | required |
| `CTB_CHAT_ID` | Forum supergroup chat ID | required |
| `CTB_ALLOWED_USER_ID` | Your Telegram user ID | required |
| `CTB_TOPIC_MODE` | `session` or `window` | `session` |
| `CTB_POLL_INTERVAL_ACTIVE` | Poll interval when active (seconds) | `0.5` |
| `CTB_POLL_INTERVAL_IDLE` | Poll interval when idle (seconds) | `2.0` |
| `CTB_TEXT_LINE_LIMIT` | Max lines per message before truncation | `30` |
| `CTB_CAFFEINATE` | Enable sleep prevention on startup | `true` |
| `CTB_OPENAI_API_KEY` | OpenAI API key for voice transcription | optional |
| `CTB_PROJECTS_DIR` | Root directory for directory browser | `~/Projects` |

## Topic Modes

**Session mode** (default): One forum topic per tmux session. Navigate windows/panes within the topic.

**Window mode**: One forum topic per tmux window. Topic names follow the format `{sess_idx}-{sess_name}-{win_idx}-{win_name}`. Switch modes at runtime with `/topic_mode`.

## Commands

| Command | Scope | Description |
|---|---|---|
| `/sessions` | Control | List all tmux sessions |
| `/new_session <name>` | Control | Create new session with directory browser |
| `/topic_mode [session\|window]` | Control | View or switch topic mode |
| `/caffeinate [on\|off]` | Control | Toggle sleep prevention |
| `/status` | Control | Bot overview |
| `/service [install\|uninstall\|status]` | Control | Manage launchd service |
| `/send <text>` | Session | Send text to focused pane |
| `/direct` | Session | Toggle direct input mode |
| `/screenshot` | Session | Render pane as PNG |
| `/claude` | Session | Show Claude Code commands menu |
| `/key <combo>` | Session | Send key combinations |
| `/new_window <name>` | Session | Create window in current session |
| `/split [h\|v]` | Session | Split focused pane |
| `/history` | Session | Browse past messages |
| `/file <path>` | Session | Send file from Mac to Telegram |

## Architecture

The bot uses a **focused pane model** — each topic has one active pane receiving full output streaming, while background panes are monitored at a lower frequency. Claude prompts from any pane surface immediately as separate messages.

**Claude Code panes** are detected via the hook system and use structured events (PreToolUse, PostToolUse, Stop, Notification, etc.) combined with JSONL transcript reading for full message content.

**Generic panes** fall back to terminal capture with ANSI stripping and prompt pattern detection.

## License

MIT
