# Telegram Bot for tmux / Claude Code Remote Control

## Context

Build a Python Telegram bot that provides full remote control of tmux sessions, primarily for interacting with Claude Code. The bot maps Telegram forum topics to tmux sessions (or windows) and uses inline keyboards for navigating windows/panes. It uses Claude Code's hook system + JSONL transcript reading for Claude-specific panes, and terminal capture for generic panes. It renders prompts, tool results, and status events as Telegram UI elements.

## Tech Stack

- **Python 3.12+** with asyncio
- **aiogram 3.x** — async Telegram bot with forum topic support
- **libtmux** — Python tmux API
- **pydantic-settings** — configuration from env vars
- **rich** — terminal output → SVG rendering for screenshots
- **cairosvg** — SVG → PNG conversion for Telegram photos
- **openai** — Whisper API for voice message transcription

## Project Structure

```
claude-tmux-bot/
├── main.py                    # Entry point, wires bot + watcher + tmux
├── config.py                  # Settings (env vars with CTB_ prefix)
├── requirements.txt           # aiogram, libtmux, pydantic-settings, rich, cairosvg, openai
├── install.sh                 # Install script (brew install cairo + pip install -r requirements.txt)
├── com.ctb.plist              # launchd service definition for macOS
├── bot/
│   ├── handlers.py            # Command & callback handlers
│   ├── keyboards.py           # Inline keyboard builders (nav, prompts, action bar)
│   ├── topics.py              # Forum topic ↔ tmux mapping (session or window mode)
│   ├── middleware.py          # User ID whitelist auth
│   ├── formatters.py         # Terminal output → Telegram message
│   └── media.py              # Voice transcription, photo/file handling
├── tmux/
│   ├── manager.py             # Session/window/pane CRUD via libtmux
│   ├── capture.py             # Pane capture + diff detection
│   └── screenshot.py          # ANSI output → PNG rendering via rich
├── claude/
│   ├── hooks.py               # Hook installer + hook event handlers
│   ├── transcript.py          # JSONL transcript reader (byte-offset tracking)
│   └── models.py              # Hook events, transcript entries
├── parser/
│   ├── ansi.py                # ANSI escape stripping (regex)
│   └── terminal.py            # Generic terminal prompt detection (fallback)
├── watcher/
│   ├── pane_watcher.py        # Async polling loop + event dispatch
│   ├── claude_watcher.py      # JSONL transcript monitor for Claude panes
│   ├── session_watcher.py     # Detects new/removed tmux sessions
│   └── state.py               # Per-topic focus, per-pane state tracking
└── tests/
    ├── test_claude_hooks.py
    ├── test_transcript.py
    ├── test_ansi.py
    └── test_watcher.py
```

## Core Features

### 1. Control Topic

A dedicated **Control** forum topic for bot-wide commands and status, created on first startup.

**Commands handled in Control topic:**
- `/sessions` — list all tmux sessions
- `/new_session <name>` — create new session
- `/topic_mode [session|window]` — switch topic mapping mode
- `/caffeinate [on|off]` — toggle sleep prevention
- `/status` — bot overview (mode, sessions, caffeinate state, uptime)
- `/service [install|uninstall|status]` — manage launchd service

**Notifications posted to Control topic:**
- Bot startup / shutdown
- Wake-from-sleep recovery
- New session detected / session ended
- Topic mode switch completed
- Errors (tmux server unavailable, etc.)

Session/window topics stay clean — only terminal output, prompts, and pane interaction.

### 2. Topic Modes — Session vs Window Mapping

Two configurable modes for how Telegram forum topics map to tmux:

| Mode | Topics created | Topic name format | Scope per topic |
|---|---|---|---|
| `session` | 1 per session | `myproject` | All windows & panes |
| `window` | 1 per window | `{sess_idx}-{sess_name}-{win_idx}-{win_name}` | Panes in that window |

**Window mode example** (2 sessions × 2 windows = 4 topics):
```
1-backend-0-code
1-backend-1-terminal
2-frontend-0-code
2-frontend-2-tests     ← tmux native index (gap-safe)
```

- Default mode set via `CTB_TOPIC_MODE` env var
- Runtime toggle via `/topic_mode` command
- Switching modes: old topics archived, new topics created
- Current mode persisted in state file (survives restarts)

### 3. Focused Pane Model

Each topic has one **focused pane** that receives full output streaming. All other panes in the topic's scope are **background-monitored**.

- **Focused pane**: full output streaming, message edits, prompt rendering
- **Background panes**: slower polling, compact activity notifications:
  `"Activity in window 'editor' / pane 1"` + **[Switch to this pane]** button
- **Claude prompts surface immediately from any pane** as separate messages, clearly labeled with their source: `"[window 'editor' / pane 1] Claude is asking for permission..."`
- Two simultaneous prompts from different panes = two separate messages, no blocking
- **Initial focus**: on topic creation, the focused pane defaults to tmux's active pane

### 4. Dual Data Source — Hooks + Terminal Capture

**Claude Code panes** (detected via hook session map):
- **Hooks registered in `~/.claude/settings.json`:**
  - `PreToolUse` → permission prompt with tool details
  - `PostToolUse` → tool result (edit original message in-place)
  - `PostToolUseFailure` → tool failure notification
  - `Stop` → task completion with cost/token summary
  - `Notification` → relay notifications (permission_prompt, idle_prompt, auth_success, elicitation_dialog)
  - `UserPromptSubmit` → track prompts sent from Telegram
  - `SessionStart` / `SessionEnd` → session lifecycle tracking
  - `SubagentStart` / `SubagentStop` → subagent activity tracking
- **JSONL transcript**: Read Claude's session transcript files with byte-offset tracking (no re-reading). Extracts assistant text, thinking blocks, tool use, tool results, cost summaries
- Hooks provide structured events; transcript provides full message content
- Thinking blocks rendered as collapsible expandable quotes

**Non-Claude panes** (generic terminals):
- Terminal capture via `tmux capture-pane` + ANSI stripping
- Generic prompt detection (command prompt, common patterns)
- Full output streaming as text

### 5. Inline Keyboard Navigation

```
/sessions → [Session buttons]
  → Tap session → [Window buttons]
    → Tap window → [Pane buttons]
      → Tap pane → [Focus] (sets as focused pane, action bar handles keys)
```

### 6. Persistent Action Bar

An **always-visible action bar** message pinned at the bottom of each session/window topic with clearly labeled buttons:

**While Claude is idle:**
```
[Escape] [Ctrl+C] [📸 Screenshot]
```

**While Claude is processing:**
```
[⏹ Stop] [Escape] [Ctrl+C] [📸 Screenshot]
```

- Auto-created when a pane is focused in a topic
- [⏹ Stop] appears only while Claude is actively working
- All buttons send corresponding keystrokes to the focused pane
- Arrow keys not needed — Claude prompts and choices are rendered as tappable inline keyboard buttons directly
- `/key <combo>` for rare key combinations (e.g., `/key up`, `/key ctrl+a`)

### 7. Text Input — Dual Mode

**Input modes:**
- **Default mode** (`/send`): use `/send <text>` to forward keystrokes to focused pane
- **Direct mode** (`/direct`): toggle auto-forwarding — all plain messages sent to the focused pane
- Mode indicator shown in status messages so user always knows current state
- `/send` always works regardless of mode

**Double-Enter for Claude Code**: When sending to a Claude pane, automatically send Enter twice (Claude TUI requirement). 500ms delay before Enter to prevent misinterpretation.

### 8. Claude Code Prompt & Output Handling

**All interactive prompt types:**

| Prompt Type | Telegram Rendering |
|---|---|
| **Permission (edit/create/delete)** | `"Edit main.py?"` + [Yes] [Always Allow] [No] [Cancel] |
| **Bash approval** | Shows command text + [Yes] [Yes, don't ask for: pattern] [No] [Cancel] |
| **AskUserQuestion (single)** | Option buttons + [✏️ Custom input...] — tap to select |
| **AskUserQuestion (multi)** | Toggleable checkboxes + [✏️ Custom input...] + [✓ Submit] |
| **ExitPlanMode** | Plan summary + action choices (see below) |
| **RestoreCheckpoint** | Checkpoint list + [Restore code] [Restore conversation] [Restore both] [Cancel] |
| **Yes/No** | [Yes] [No] |
| **Text input** | Bot asks user to type a reply |

- "Always Allow" text varies by context (e.g., "allow all edits this session" vs "don't ask again for: npm run *")
- **ExitPlanMode options** are context-dependent numbered choices, rendered as buttons:
  ```
  [Implement]
  [Clear context and implement]
  [Continue but accept edits]
  [Edit plan (Ctrl+G)]
  [Cancel]
  ```
  The exact options vary — bot reads the numbered list from the prompt and renders whatever options Claude presents as buttons

**Status indicators (non-interactive):**

| Output Type | Telegram Rendering |
|---|---|
| **Spinner/status line** | `"✻ Reading file..."` shown in topic as status update |
| **Tool running** | `"🔧 Running Edit on main.py..."` → edited in-place with result when done |
| **Tool failure** | `"❌ Edit failed: ..."` (edit the tool running message) |
| **Thinking blocks** | Collapsible expandable quotes |
| **Task completion** | Notification with cost/token summary |
| **Subagent activity** | `"Spawned subagent for..."` / `"Subagent finished"` |
| **Permission mode** | Show current mode (default, acceptEdits, plan) in status |

**Via terminal capture** (fallback, for non-Claude panes or if hooks fail):
- **Permission prompts**: "Do you want to" + numbered options → inline keyboard
- **Bash approval**: "Bash command" header + command text → inline keyboard
- **AskUserQuestion**: checkbox/radio icons (☐/✔) → inline keyboard
- **ExitPlanMode**: "Would you like to proceed?" → inline keyboard
- **RestoreCheckpoint**: "Restore the code" → inline keyboard
- **Idle prompt**: `❯` at end of output

### 9. Output Streaming

**Polling & debounce:**
- Adaptive polling: 500ms when active, 2s when idle
- 1.5s debounce to batch streaming output
- Rate limit: respect Telegram's ~30 edits/min/chat

**Message format:**
- Each output update sent as a **text message** (monospace) showing the latest diff
- Truncated to `CTB_TEXT_LINE_LIMIT` lines (configurable, default: 30)
- If truncated → **[Screenshot]** inline button appended below the message
- Tapping [Screenshot] renders full terminal viewport as PNG and sends it
- Claude prompts & status events → always separate text messages with inline keyboards (never truncated)

**Tool result editing:**
- When a tool starts → send message: `"🔧 Running Edit on main.py..."`
- When tool finishes → **edit that same message** with the result summary
- Keeps chat compact, avoids message spam

**Typing indicator:**
- Send Telegram "typing" action while Claude is actively processing
- Stops when Claude returns to idle or shows a prompt

### 10. Pane Screenshot

`/screenshot` renders the focused pane as a PNG image and sends it as a Telegram photo.

- Uses `tmux capture-pane -e -p` to get ANSI-colored output
- Renders to PNG via **rich** (Console → export SVG) + **cairosvg** (SVG → PNG)
- Preserves colors, layout, and cursor position — looks like an actual terminal
- Also used by the **[Screenshot]** button on truncated output messages

### 11. Claude Commands Menu

`/claude` shows an inline keyboard with Claude Code's built-in slash commands:

```
[/compact] [/clear]  [/cost]
[/model]   [/memory]  [/rewind]
[/settings] [/help]   [/doctor]
```

- Tap a button → bot sends that command as keystrokes to the focused pane
- Only shown in topics where the focused pane is running Claude Code
- Commands that open interactive UIs (e.g., `/rewind` → RestoreCheckpoint, `/settings` → Settings overlay) are handled by the prompt detection system

### 12. Voice Messages

- User sends a voice message in a session/window topic
- Bot downloads the audio, transcribes via **OpenAI Whisper API**
- Transcribed text forwarded to the focused pane as keystrokes
- Bot replies with the transcription so user can verify what was sent
- Requires `CTB_OPENAI_API_KEY` env var

### 13. Photo & File Transfer

**Telegram → Mac:**
- Photos sent in a topic are downloaded and saved to `~/.ctb/media/`
- File path sent to Claude as text input (Claude can read images)
- Files (documents) saved similarly, path forwarded

**Mac → Telegram:**
- `/file <path>` sends a file from the Mac to Telegram
- Files under 50MB sent directly via Telegram API

### 14. Directory Browser

When creating a session with `/new_session`:
- Bot shows a **paginated directory browser** (6 dirs per page)
- Navigate with inline keyboard: folder buttons, [⬆️ Up], [Next ➡️]
- Select a directory → session created with that working directory
- Configurable root via `CTB_PROJECTS_DIR` env var

### 15. Session/Window/Pane Management from Telegram

- `/new_session <name>` — create a tmux session with default shell (auto-creates topic)
- `/new_window <name>` — add window to current topic's session
- `/split [h|v]` — split focused pane horizontally or vertically
- `/kill_session`, `/kill_window`, `/kill_pane` — cleanup commands
- Also available as inline keyboard actions where appropriate

### 16. Message History

- `/history` — paginated browsing of past messages in the topic
- Newest-first ordering with [⬅️ Older] [Newer ➡️] buttons
- Shows timestamps and role indicators (user/assistant)
- Page numbers displayed

### 17. Auto-Sync & Startup

On startup (including after crash/restart/reboot):
1. Load state file (topic mappings, current mode, focus state)
2. Install/verify Claude Code hooks in `~/.claude/settings.json`
3. Discover all existing tmux sessions
4. Create topics for any unmapped sessions/windows
5. Remove stale mappings for sessions/windows that no longer exist
6. Start watching **all** panes automatically — no manual `/watch` needed

**Session discovery loop** (runs continuously):
- Polls tmux for new/removed sessions and windows
- Auto-creates topics for new ones
- Cleans up topics for removed ones (archive, don't delete)

### 18. Sleep Prevention & Recovery

Controllable from Telegram — never need to touch the Mac.

- **`/caffeinate on`** — spawns `caffeinate -i` subprocess, Mac stays awake
- **`/caffeinate off`** — kills `caffeinate`, Mac can sleep naturally
- Default on startup set via `CTB_CAFFEINATE` env var (default: `true`)
- Screen lock is unaffected — lock screen freely, processes keep running
- **Wake recovery**: when Mac wakes from sleep, bot detects it and re-syncs:
  reconnect to tmux, rediscover sessions, resume watching all panes
- Wake detection via monitoring system uptime or a heartbeat timer gap

### 19. launchd Service

Install as a macOS service for persistent operation:

- `/service install` — installs `com.ctb.plist` to `~/Library/LaunchAgents/`
- `/service uninstall` — removes the service
- `/service status` — check if service is running
- **KeepAlive**: auto-restarts if bot crashes
- **RunAtLoad**: starts on login
- `install.sh` handles both service installation and dependency setup

### 20. Security

- Single allowed Telegram user ID (whitelist middleware)
- All non-whitelisted messages silently ignored

## Configuration (env vars)

| Variable | Description | Default |
|---|---|---|
| `CTB_BOT_TOKEN` | Telegram bot token | required |
| `CTB_CHAT_ID` | Forum supergroup chat ID | required |
| `CTB_ALLOWED_USER_ID` | Your Telegram user ID | required |
| `CTB_TOPIC_MODE` | `session` or `window` | `session` |
| `CTB_POLL_INTERVAL_ACTIVE` | Poll interval when active | `0.5` |
| `CTB_POLL_INTERVAL_IDLE` | Poll interval when idle | `2.0` |
| `CTB_OUTPUT_DEBOUNCE` | Debounce window for streaming | `1.5` |
| `CTB_TEXT_LINE_LIMIT` | Max lines per text message before truncation | `30` |
| `CTB_CAFFEINATE` | Enable sleep prevention on startup | `true` |
| `CTB_OPENAI_API_KEY` | OpenAI API key for Whisper voice transcription | optional |
| `CTB_PROJECTS_DIR` | Root directory for directory browser | `~/Projects` |
| `CTB_STATE_FILE` | Path to state file | `~/.ctb/state.json` |

## Watcher State Model

```python
@dataclass
class BotState:
    topic_mode: str                    # "session" or "window"
    control_topic_id: int              # Telegram topic ID for the Control topic
    caffeinate_active: bool            # is caffeinate subprocess running
    topics: dict[str, TopicState]      # keyed by tmux_target

@dataclass
class TopicState:
    topic_id: int              # Telegram forum topic ID
    tmux_target: str           # session name (session mode) or session:window (window mode)
    focused_pane_id: str       # currently focused pane
    direct_mode: bool          # auto-forward messages to focused pane
    action_bar_msg_id: int | None  # Telegram message ID of the persistent action bar
    panes: dict[str, PaneState]

@dataclass
class PaneState:
    pane_id: str
    content_hash: str          # last known content hash
    last_change: float         # timestamp of last change
    pending_prompt: Prompt | None  # detected prompt not yet surfaced
    is_focused: bool           # is this the focused pane in its topic
    is_claude: bool            # is this pane running Claude Code (use hooks+JSONL)
    transcript_offset: int     # byte offset for JSONL reading (Claude panes only)
    tool_msg_ids: dict[str, int]  # tool_use_id → Telegram message ID for in-place editing
```

## Command Routing

Commands are scoped to the topic they're sent in:

**Control topic only:**
`/sessions`, `/new_session`, `/topic_mode`, `/caffeinate`, `/status`, `/service`

**Session/window topics only:**
`/send`, `/direct`, `/capture`, `/screenshot`, `/key`, `/claude`, `/new_window`, `/split`, `/kill_pane`, `/kill_window`, `/kill_session`, `/history`, `/file`

If a command is sent in the wrong topic, the bot replies with a brief redirect:
`"This command works in the Control topic"` or `"This command works in a session topic"`.

## Implementation Order

### Phase 1: Foundation
1. `config.py` — pydantic-settings schema with all env vars
2. `parser/ansi.py` — ANSI stripping regex
3. `tmux/manager.py` — TmuxManager (list/create/kill sessions/windows/panes, capture, send_keys with double-Enter for Claude)
4. `tmux/capture.py` — PaneCapture with content hash diff
5. `requirements.txt` + `install.sh`

### Phase 2: Claude Code Integration
6. `claude/models.py` — hook event types, transcript entry types
7. `claude/hooks.py` — install hooks in ~/.claude/settings.json, handle hook events
8. `claude/transcript.py` — JSONL reader with byte-offset tracking, extract assistant text, tool use, thinking blocks
9. `tests/test_claude_hooks.py` + `tests/test_transcript.py`

### Phase 3: Terminal Fallback Parser
10. `parser/terminal.py` — detect all prompt types by terminal text: PermissionPrompt, BashApproval, AskUserQuestion (single/multi), ExitPlanMode, RestoreCheckpoint, idle prompt
11. `tests/test_ansi.py` + `tests/test_terminal_parser.py`

### Phase 4: Telegram Bot
12. `bot/middleware.py` — AuthMiddleware
13. `bot/topics.py` — TopicManager (create/sync/lookup, session & window mode, mode switching)
14. `bot/keyboards.py` — Navigation + prompt (permission, choices, plan, checkpoint) + action bar + directory browser + Claude commands menu keyboards
15. `bot/formatters.py` — Terminal output, prompt, tool result, thinking block formatting
16. `bot/media.py` — Voice transcription (Whisper), photo/file download + forwarding
17. `bot/handlers.py` — All commands + callbacks + action bar buttons

### Phase 5: Watchers + Integration
18. `watcher/state.py` — BotState, TopicState, PaneState, StateManager (load/save/update)
19. `watcher/session_watcher.py` — Async loop detecting new/removed sessions & windows
20. `watcher/claude_watcher.py` — JSONL transcript monitor, tool result in-place editing, action bar management
21. `watcher/pane_watcher.py` — Terminal capture poll loop for non-Claude panes
22. `tmux/screenshot.py` — ANSI → SVG → PNG rendering
23. `main.py` — Wire bot + watchers + tmux + hooks, startup sync, graceful shutdown

### Phase 6: Service & Polish
24. `com.ctb.plist` — launchd service definition
25. Service install/uninstall/status commands
26. Error handling (session dies mid-watch, Telegram rate limits, tmux server not running)
27. Graceful shutdown (cancel watchers, save state, kill caffeinate)
28. Edge cases (topic mode switch while prompts pending, pane dies while focused, hook installation conflicts)

## Commands Reference

| Command | Description |
|---|---|
| `/sessions` | List all tmux sessions |
| `/new_session <name>` | Create new tmux session (with directory browser) |
| `/send <text>` | Send text to focused pane |
| `/direct` | Toggle direct mode (auto-forward messages) |
| `/capture` | Capture and display current focused pane output |
| `/screenshot` | Render focused pane as PNG image and send |
| `/new_window <name>` | Create new window in current session |
| `/split [h\|v]` | Split focused pane |
| `/kill_session` | Kill current session |
| `/kill_window` | Kill current window |
| `/kill_pane` | Kill focused pane |
| `/topic_mode [session\|window]` | View or switch topic mode |
| `/caffeinate [on\|off]` | Toggle sleep prevention |
| `/status` | Show bot status (mode, focused panes, direct mode state) |
| `/history` | Browse past messages with pagination |
| `/file <path>` | Send a file from Mac to Telegram |
| `/key <combo>` | Send rare key combinations (e.g., `/key ctrl+a`, `/key up`) |
| `/claude` | Show Claude Code commands menu (/compact, /clear, /cost, /model, etc.) |
| `/service [install\|uninstall\|status]` | Manage launchd service |

## Verification

1. Create a Telegram supergroup with forum topics enabled
2. Add the bot as admin with `can_manage_topics` permission
3. Run `./install.sh` to install dependencies
4. Set env vars and run `python main.py`
5. Bot auto-creates Control topic + topics for all existing tmux sessions
6. Open a topic — focused pane output streams automatically
7. Claude hooks installed — tool use appears as editable messages
8. Send a voice message → transcribed and forwarded to Claude
9. Send a photo → saved, path sent to Claude
10. Claude processing → action bar shows [⏹ Stop] [Escape] [Ctrl+C] [📸 Screenshot]
11. Claude shows permission prompt → [Yes] [Always Allow] [No] [Cancel]
12. Claude shows bash approval → command text + [Yes] [Yes, don't ask for: pattern] [No]
13. Claude shows multi-select → toggleable checkboxes with [✏️ Custom input...] and [✓ Submit]
14. Claude presents plan (ExitPlanMode) → dynamic buttons: [Implement] [Clear context and implement] etc.
15. `/claude` → inline keyboard with Claude slash commands → tap sends to pane
16. Tool finishes → original "tool running" message edited with result
17. Output exceeds line limit → [Screenshot] button appears
18. `/topic_mode window` → topics reorganized per-window
19. `/new_session test` → directory browser → select folder → session created
20. `/direct` → type a message → it goes straight to the pane
21. `/history` → paginated message browsing
22. `/file ~/Documents/test.txt` → file sent to Telegram
23. Kill a tmux session → topic is archived, mapping cleaned up
24. Restart bot → state restored, all panes watched again
25. `/service install` → bot runs as launchd service, survives reboots
