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
- **Wake Recovery** — Detects Mac wake from sleep, re-syncs sessions, resumes watching
- **launchd Service** — Install as a macOS service that auto-starts on login and survives reboots
- **Auto-Sync** — On startup, discovers all tmux sessions, creates topics, installs hooks, and resumes watching

## Tech Stack

- **Python 3.9+** with asyncio
- **aiogram 3.x** — async Telegram bot with forum topic support
- **libtmux** — Python tmux API
- **pydantic-settings** — configuration from env vars / `.env` file
- **rich** + **cairosvg** — terminal output to PNG rendering
- **openai** — Whisper API for voice transcription

## Quick Start

### Prerequisites

- **Python 3.9+** and **tmux** installed
- A **Telegram account**

### Setup

```bash
git clone https://github.com/launch52-ai/claude-tmux-bot.git
cd claude-tmux-bot
chmod +x install.sh && ./install.sh
```

The install script guides you through everything:

1. Installs dependencies (cairo, Python packages)
2. Walks you through creating a Telegram bot via @BotFather
3. Walks you through creating a supergroup with Topics
4. Auto-detects your chat ID and user ID (just send a message in the group)
5. Saves everything to `.env`

After setup, start the bot:

```bash
tmux new-session -d -s main   # if no tmux sessions exist yet
python3 main.py
```

### Install as a service (optional)

From Telegram, send `/service install` in the Control topic. The bot will auto-start on login and restart on crash.

### Uninstall

```bash
./uninstall.sh
```

Removes the launchd service, Claude Code hooks, `~/.ctb` data, and `.env`. Prompts before deleting data.

## Configuration

All configuration is via environment variables (with `CTB_` prefix) or a `.env` file in the project root.

| Variable | Description | Default |
|---|---|---|
| `CTB_BOT_TOKEN` | Telegram bot token | required |
| `CTB_CHAT_ID` | Forum supergroup chat ID | required |
| `CTB_ALLOWED_USER_ID` | Your Telegram user ID | required |
| `CTB_TOPIC_MODE` | `session` or `window` | `session` |
| `CTB_TOPIC_CLEANUP` | `close` or `delete` stale topics | `close` |
| `CTB_POLL_INTERVAL_ACTIVE` | Poll interval when active (seconds) | `0.5` |
| `CTB_POLL_INTERVAL_IDLE` | Poll interval when idle (seconds) | `2.0` |
| `CTB_OUTPUT_DEBOUNCE` | Debounce window for streaming (seconds) | `1.5` |
| `CTB_TEXT_LINE_LIMIT` | Max lines per message before truncation | `30` |
| `CTB_CAFFEINATE` | Enable sleep prevention on startup | `true` |
| `CTB_OPENAI_API_KEY` | OpenAI API key for voice transcription | optional |
| `CTB_PROJECTS_DIR` | Root directory for directory browser | `~/Projects` |
| `CTB_STATE_FILE` | Path to state persistence file | `~/.ctb/state.json` |
| `CTB_MEDIA_DIR` | Path for downloaded media files | `~/.ctb/media` |

## Topic Modes

**Session mode** (default): One forum topic per tmux session. Topic names follow the format `{sess_idx}-{sess_name}`. Navigate windows/panes within the topic.

**Window mode**: One forum topic per tmux window. Topic names follow the format `{sess_idx}-{sess_name}-{win_idx}-{win_name}`. Switch modes at runtime with `/topic_mode`.

Stale topics (from killed sessions/windows) are closed by default. Set `CTB_TOPIC_CLEANUP=delete` to permanently delete them instead.

## Commands

### Control topic

| Command | Description |
|---|---|
| `/sessions` | List all tmux sessions |
| `/new_session <name>` | Create new session with directory browser |
| `/topic_mode [session\|window]` | View or switch topic mode |
| `/caffeinate [on\|off]` | Toggle sleep prevention |
| `/status` | Bot overview (mode, uptime, focused panes, direct mode) |
| `/service [install\|uninstall\|status]` | Manage launchd service |

### Session/window topics

| Command | Description |
|---|---|
| `/send <text>` | Send text to focused pane |
| `/direct` | Toggle direct input mode (all messages forwarded to pane) |
| `/capture` | Capture and display current pane output |
| `/screenshot` | Render pane as PNG image |
| `/claude` | Show Claude Code slash commands menu |
| `/key <combo>` | Send key combinations (e.g., `/key ctrl+c`, `/key up`) |
| `/new_window <name>` | Create window in current session |
| `/split [h\|v]` | Split focused pane |
| `/kill_pane` | Kill focused pane |
| `/kill_window` | Kill focused window |
| `/kill_session` | Kill current session |
| `/history` | Browse past transcript messages with pagination |
| `/file <path>` | Send file from Mac to Telegram |

## How It Works

### Focused Pane Model

Each topic has one **focused pane** receiving full output streaming. Background panes are monitored at a lower frequency — activity shows as compact notifications with a **[Switch to this pane]** button. Claude prompts from any pane surface immediately.

### Claude Code Integration

Claude Code panes are detected via the hook system. The bot installs hooks in `~/.claude/settings.json` that capture all 10 event types (PreToolUse, PostToolUse, Stop, Notification, etc.). Hook events are combined with JSONL transcript reading for full message content including thinking blocks.

- Tool use → editable "Running..." message → edited in-place with result
- Permission prompts → inline keyboard with Yes / Always Allow / No / Cancel
- Thinking blocks → expandable blockquotes
- Task completion → cost/token summary

### Generic Panes

Non-Claude panes fall back to terminal capture with ANSI stripping and regex-based prompt detection for permission prompts, bash approvals, multi-select questions, and more.

## Project Structure

```
├── main.py              # Entry point — wires bot + watchers + tmux
├── config.py            # Settings (env vars / .env with CTB_ prefix)
├── service.py           # macOS launchd service management
├── com.claude-tmux-bot.plist        # launchd plist template
├── bot/
│   ├── handlers.py      # Command & callback handlers
│   ├── keyboards.py     # Inline keyboard builders
│   ├── topics.py        # Forum topic ↔ tmux mapping
│   ├── middleware.py     # User ID whitelist auth
│   ├── formatters.py    # Output formatting for Telegram
│   └── media.py         # Voice transcription, photo/file handling
├── tmux/
│   ├── manager.py       # Session/window/pane CRUD via libtmux
│   ├── capture.py       # Pane capture + diff detection
│   └── screenshot.py    # ANSI → SVG → PNG rendering
├── claude/
│   ├── hooks.py         # Hook installer + event watcher
│   ├── transcript.py    # JSONL transcript reader
│   └── models.py        # Hook event & transcript types
├── parser/
│   ├── ansi.py          # ANSI escape stripping
│   └── terminal.py      # Terminal prompt detection
├── watcher/
│   ├── state.py         # Bot/topic/pane state + persistence
│   ├── session_watcher.py  # Detects new/removed sessions
│   ├── claude_watcher.py   # Hook event processing
│   └── pane_watcher.py     # Terminal capture polling
└── tests/
    ├── test_ansi.py
    ├── test_terminal_parser.py
    ├── test_claude_hooks.py
    ├── test_transcript.py
    └── test_watcher.py
```

## Testing

```bash
python3 -m pytest tests/ -v
```

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.
