# Claude Tmux Bot

## Project Overview
Telegram bot for remote-controlling tmux sessions, primarily for interacting with Claude Code.

## Tech Stack
- Python 3.9+ with asyncio
- aiogram 3.x (Telegram bot)
- libtmux (tmux API)
- pydantic-settings (configuration)
- rich + cairosvg (terminal screenshots)

## Architecture
- `bot/` — Telegram bot (handlers, keyboards, formatters, middleware, topics, media)
- `tmux/` — tmux management (manager, capture, screenshot)
- `claude/` — Claude Code integration (hooks, transcript reader, models)
- `parser/` — ANSI stripping and terminal prompt detection
- `watcher/` — State management and async watchers (session, claude, pane)
- `main.py` — Entry point
- `config.py` — Settings via CTB_ env vars
- `service.py` — macOS launchd service management

## Conventions
- All env vars use `CTB_` prefix
- Use `Optional[T]` instead of `T | None` for Python 3.9 compatibility (pydantic runtime evaluation)
- Use `Union[A, B]` instead of `A | B` for type aliases evaluated at runtime
- `from __future__ import annotations` is fine for non-pydantic modules
- Tests in `tests/` — run with `CTB_BOT_TOKEN=test CTB_CHAT_ID=1 CTB_ALLOWED_USER_ID=1 python3 -m pytest tests/ -v`

## Running
```bash
./install.sh
export CTB_BOT_TOKEN=... CTB_CHAT_ID=... CTB_ALLOWED_USER_ID=...
python3 main.py
```
