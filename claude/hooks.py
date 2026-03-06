from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Coroutine

from claude.models import (
    HookEvent,
    HookPayload,
    StopEvent,
    SubagentEvent,
    ToolResultEvent,
    ToolUseEvent,
)

logger = logging.getLogger(__name__)

_HOOKS_DIR = Path.home() / ".ctb" / "hooks"
_EVENTS_DIR = Path.home() / ".ctb" / "hook_events"
_HOOK_SCRIPT = _HOOKS_DIR / "ctb_hook.sh"
_CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"

HookCallback = Callable[[HookPayload], Coroutine[Any, Any, None]]


def _get_hook_script_content() -> str:
    return f"""#!/usr/bin/env bash
# Claude Code hook — writes event to file for CTB bot
set -euo pipefail

INPUT=$(cat)
EVENT_TYPE="${{1:-unknown}}"
TIMESTAMP=$(date +%s%N)
PANE_ID="${{TMUX_PANE:-unknown}}"
SESSION_ID=$(echo "$INPUT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('session_id',''))" 2>/dev/null || echo "")

EVENT_FILE="{_EVENTS_DIR}/${{TIMESTAMP}}_${{EVENT_TYPE}}.json"

cat > "$EVENT_FILE" <<EEOF
{{
  "event": "$EVENT_TYPE",
  "session_id": "$SESSION_ID",
  "pane_id": "$PANE_ID",
  "timestamp": $(date +%s),
  "data": $INPUT
}}
EEOF

# Output empty JSON to not interfere with Claude
echo '{{}}'
"""


def install_hooks() -> None:
    _HOOKS_DIR.mkdir(parents=True, exist_ok=True)
    _EVENTS_DIR.mkdir(parents=True, exist_ok=True)

    _HOOK_SCRIPT.write_text(_get_hook_script_content())
    _HOOK_SCRIPT.chmod(0o755)

    _update_claude_settings()
    logger.info("Claude Code hooks installed")


def _update_claude_settings() -> None:
    settings: dict[str, Any] = {}
    if _CLAUDE_SETTINGS.exists():
        try:
            settings = json.loads(_CLAUDE_SETTINGS.read_text())
        except (json.JSONDecodeError, OSError):
            settings = {}

    hooks = settings.setdefault("hooks", {})
    script = str(_HOOK_SCRIPT)

    # New hooks format: each event is an array of {matcher, hooks} objects
    # matcher: {} means match all (no filtering)
    # hooks: array of hook commands
    event_names = [
        HookEvent.PRE_TOOL_USE.value,
        HookEvent.POST_TOOL_USE.value,
        HookEvent.POST_TOOL_USE_FAILURE.value,
        HookEvent.STOP.value,
        HookEvent.NOTIFICATION.value,
        HookEvent.USER_PROMPT_SUBMIT.value,
        HookEvent.SESSION_START.value,
        HookEvent.SESSION_END.value,
        HookEvent.SUBAGENT_START.value,
        HookEvent.SUBAGENT_STOP.value,
    ]

    for event_name in event_names:
        hook_command = {"type": "command", "command": f"{script} {event_name}"}
        existing = hooks.get(event_name, [])
        if not isinstance(existing, list):
            existing = [existing]

        # Migrate old-format CTB entries and check if already installed
        already_installed = False
        migrated: list[dict] = []
        for entry in existing:
            if not isinstance(entry, dict):
                migrated.append(entry)
                continue

            entry_hooks = entry.get("hooks")
            if isinstance(entry_hooks, list):
                # Already new format
                if any(
                    isinstance(h, dict) and h.get("command", "").startswith(script)
                    for h in entry_hooks
                ):
                    already_installed = True
                migrated.append(entry)
            elif entry.get("command", "").startswith(script):
                # Old-format CTB entry — migrate to new format
                migrated.append({
                    "matcher": {},
                    "hooks": [{"type": entry.get("type", "command"), "command": entry["command"]}],
                })
                already_installed = True
            else:
                # Old-format entry from another tool — migrate it too
                if "command" in entry:
                    migrated.append({
                        "matcher": {},
                        "hooks": [entry],
                    })
                else:
                    migrated.append(entry)

        if not already_installed:
            migrated.append({
                "matcher": {},
                "hooks": [hook_command],
            })

        hooks[event_name] = migrated

    settings["hooks"] = hooks
    _CLAUDE_SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    _CLAUDE_SETTINGS.write_text(json.dumps(settings, indent=2) + "\n")


def uninstall_hooks() -> None:
    if not _CLAUDE_SETTINGS.exists():
        return

    try:
        settings = json.loads(_CLAUDE_SETTINGS.read_text())
    except (json.JSONDecodeError, OSError):
        return

    hooks = settings.get("hooks", {})
    script = str(_HOOK_SCRIPT)

    for event_name in list(hooks.keys()):
        entries = hooks[event_name]
        if not isinstance(entries, list):
            continue

        cleaned = []
        for entry in entries:
            if not isinstance(entry, dict):
                cleaned.append(entry)
                continue

            # New format: {matcher, hooks: [...]}
            entry_hooks = entry.get("hooks")
            if isinstance(entry_hooks, list):
                filtered = [
                    h for h in entry_hooks
                    if not (isinstance(h, dict) and h.get("command", "").startswith(script))
                ]
                if filtered:
                    entry["hooks"] = filtered
                    cleaned.append(entry)
                # If no hooks left, drop the entire entry
            # Old format: direct {type, command}
            elif not entry.get("command", "").startswith(script):
                cleaned.append(entry)

        if cleaned:
            hooks[event_name] = cleaned
        else:
            del hooks[event_name]

    settings["hooks"] = hooks
    _CLAUDE_SETTINGS.write_text(json.dumps(settings, indent=2) + "\n")
    logger.info("Claude Code hooks uninstalled")


def parse_hook_event(filepath: Path) -> HookPayload | None:
    try:
        raw = json.loads(filepath.read_text())
        return HookPayload(
            event=HookEvent(raw["event"]),
            session_id=raw.get("session_id", ""),
            pane_id=raw.get("pane_id", ""),
            timestamp=float(raw.get("timestamp", time.time())),
            data=raw.get("data", {}),
        )
    except Exception:
        logger.exception("Failed to parse hook event: %s", filepath)
        return None


def parse_tool_use(payload: HookPayload) -> ToolUseEvent:
    data = payload.data
    tool_input = data.get("input", {}) if isinstance(data.get("input"), dict) else {}
    return ToolUseEvent(
        tool_use_id=data.get("tool_use_id", ""),
        tool_name=data.get("tool_name", data.get("name", "")),
        file_path=tool_input.get("file_path") or tool_input.get("path"),
        command=tool_input.get("command"),
        input_summary=_summarize_tool_input(data.get("tool_name", ""), tool_input),
    )


def parse_tool_result(payload: HookPayload) -> ToolResultEvent:
    data = payload.data
    return ToolResultEvent(
        tool_use_id=data.get("tool_use_id", ""),
        tool_name=data.get("tool_name", data.get("name", "")),
        success=payload.event != HookEvent.POST_TOOL_USE_FAILURE,
        output_summary=str(data.get("output", ""))[:500],
        error=data.get("error"),
    )


def parse_stop_event(payload: HookPayload) -> StopEvent:
    data = payload.data
    return StopEvent(
        session_id=payload.session_id,
        cost_usd=data.get("cost_usd", 0.0),
        input_tokens=data.get("input_tokens", 0),
        output_tokens=data.get("output_tokens", 0),
        duration_ms=data.get("duration_ms", 0),
    )


def parse_subagent_event(payload: HookPayload) -> SubagentEvent:
    data = payload.data
    return SubagentEvent(
        session_id=payload.session_id,
        subagent_id=data.get("subagent_id", ""),
        description=data.get("description", ""),
    )


def _summarize_tool_input(tool_name: str, tool_input: dict) -> str:
    if "file_path" in tool_input:
        return tool_input["file_path"]
    if "path" in tool_input:
        return tool_input["path"]
    if "command" in tool_input:
        cmd = tool_input["command"]
        return cmd[:100] + ("..." if len(cmd) > 100 else "")
    if "query" in tool_input:
        return tool_input["query"][:100]
    return ""


class HookEventWatcher:
    def __init__(self, callback: HookCallback, poll_interval: float = 0.3) -> None:
        self._callback = callback
        self._poll_interval = poll_interval
        self._running = False
        self._processed: set[str] = set()

    async def start(self) -> None:
        _EVENTS_DIR.mkdir(parents=True, exist_ok=True)
        self._running = True
        logger.info("Hook event watcher started")
        while self._running:
            await self._poll()
            await asyncio.sleep(self._poll_interval)

    async def _poll(self) -> None:
        try:
            for filepath in sorted(_EVENTS_DIR.iterdir()):
                if filepath.name in self._processed:
                    continue
                if not filepath.suffix == ".json":
                    continue

                payload = parse_hook_event(filepath)
                if payload is not None:
                    try:
                        await self._callback(payload)
                    except Exception:
                        logger.exception("Error processing hook event: %s", filepath.name)

                self._processed.add(filepath.name)
                # Clean up old event files
                try:
                    filepath.unlink()
                except OSError:
                    pass

            # Prevent unbounded growth of processed set
            if len(self._processed) > 10000:
                self._processed.clear()
        except FileNotFoundError:
            pass

    def stop(self) -> None:
        self._running = False
