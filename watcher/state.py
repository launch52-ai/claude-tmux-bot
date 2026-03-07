from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PaneState:
    pane_id: str
    content_hash: str = ""
    last_change: float = 0.0
    is_focused: bool = False
    is_claude: bool = False
    transcript_offset: int = 0
    pending_prompt: str = ""
    tool_msg_ids: dict[str, int] = field(default_factory=dict)


@dataclass
class TopicState:
    topic_id: int
    tmux_target: str
    focused_pane_id: str = ""
    direct_mode: bool = False
    action_bar_msg_id: int | None = None
    panes: dict[str, PaneState] = field(default_factory=dict)


@dataclass
class BotState:
    topic_mode: str = "session"
    control_topic_id: int | None = None
    control_status_msg_id: int | None = None
    caffeinate_active: bool = False
    topics: dict[str, TopicState] = field(default_factory=dict)
    display_names: dict[str, str] = field(default_factory=dict)


class StateManager:
    def __init__(self, state_file: Path) -> None:
        self._state_file = state_file
        self._bot_state = BotState()
        self._caffeinate_proc: subprocess.Popen | None = None  # type: ignore[type-arg]

    @property
    def bot_state(self) -> BotState:
        return self._bot_state

    def load(self) -> None:
        if not self._state_file.exists():
            return
        try:
            raw = json.loads(self._state_file.read_text())
            self._bot_state.topic_mode = raw.get("topic_mode", "session")
            self._bot_state.control_topic_id = raw.get("control_topic_id")
            self._bot_state.control_status_msg_id = raw.get("control_status_msg_id")
            self._bot_state.caffeinate_active = raw.get("caffeinate_active", False)
            self._bot_state.display_names = raw.get("display_names", {})

            for target, ts_raw in raw.get("topics", {}).items():
                panes = {}
                for pid, ps_raw in ts_raw.get("panes", {}).items():
                    panes[pid] = PaneState(
                        pane_id=ps_raw.get("pane_id", pid),
                        content_hash=ps_raw.get("content_hash", ""),
                        last_change=ps_raw.get("last_change", 0.0),
                        is_focused=ps_raw.get("is_focused", False),
                        is_claude=ps_raw.get("is_claude", False),
                        transcript_offset=ps_raw.get("transcript_offset", 0),
                        tool_msg_ids=ps_raw.get("tool_msg_ids", {}),
                    )
                self._bot_state.topics[target] = TopicState(
                    topic_id=ts_raw.get("topic_id", 0),
                    tmux_target=target,
                    focused_pane_id=ts_raw.get("focused_pane_id", ""),
                    direct_mode=ts_raw.get("direct_mode", False),
                    action_bar_msg_id=ts_raw.get("action_bar_msg_id"),
                    panes=panes,
                )
            logger.info("State loaded from %s", self._state_file)
        except Exception:
            logger.exception("Failed to load state")

    def save(self) -> None:
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {
            "topic_mode": self._bot_state.topic_mode,
            "control_topic_id": self._bot_state.control_topic_id,
            "control_status_msg_id": self._bot_state.control_status_msg_id,
            "caffeinate_active": self._bot_state.caffeinate_active,
            "display_names": self._bot_state.display_names,
            "topics": {},
        }
        for target, ts in self._bot_state.topics.items():
            panes_data = {}
            for pid, ps in ts.panes.items():
                panes_data[pid] = asdict(ps)
            data["topics"][target] = {
                "topic_id": ts.topic_id,
                "tmux_target": ts.tmux_target,
                "focused_pane_id": ts.focused_pane_id,
                "direct_mode": ts.direct_mode,
                "action_bar_msg_id": ts.action_bar_msg_id,
                "panes": panes_data,
            }
        self._state_file.write_text(json.dumps(data, indent=2) + "\n")

    # -- Focus management --

    def get_focused_pane(self, topic_id: int) -> str | None:
        for ts in self._bot_state.topics.values():
            if ts.topic_id == topic_id:
                return ts.focused_pane_id or None
        return None

    def set_focused_pane(self, topic_id: int, pane_id: str) -> None:
        for ts in self._bot_state.topics.values():
            if ts.topic_id == topic_id:
                # Unfocus previous
                if ts.focused_pane_id and ts.focused_pane_id in ts.panes:
                    ts.panes[ts.focused_pane_id].is_focused = False
                ts.focused_pane_id = pane_id
                if pane_id in ts.panes:
                    ts.panes[pane_id].is_focused = True
                self.save()
                return

    def is_claude_pane(self, pane_id: str) -> bool:
        for ts in self._bot_state.topics.values():
            ps = ts.panes.get(pane_id)
            if ps is not None:
                return ps.is_claude
        return False

    def mark_claude_pane(self, pane_id: str, is_claude: bool) -> None:
        for ts in self._bot_state.topics.values():
            ps = ts.panes.get(pane_id)
            if ps is not None:
                ps.is_claude = is_claude
                return

    # -- Direct mode --

    def is_direct_mode(self, topic_id: int) -> bool:
        for ts in self._bot_state.topics.values():
            if ts.topic_id == topic_id:
                return ts.direct_mode
        return False

    def toggle_direct_mode(self, topic_id: int) -> bool:
        for ts in self._bot_state.topics.values():
            if ts.topic_id == topic_id:
                ts.direct_mode = not ts.direct_mode
                self.save()
                return ts.direct_mode
        return False

    # -- Topic state --

    def get_topic_state(self, topic_id: int) -> TopicState | None:
        for ts in self._bot_state.topics.values():
            if ts.topic_id == topic_id:
                return ts
        return None

    def get_topic_by_target(self, tmux_target: str) -> TopicState | None:
        return self._bot_state.topics.get(tmux_target)

    def ensure_topic_state(self, tmux_target: str, topic_id: int) -> TopicState:
        if tmux_target not in self._bot_state.topics:
            self._bot_state.topics[tmux_target] = TopicState(
                topic_id=topic_id,
                tmux_target=tmux_target,
            )
        return self._bot_state.topics[tmux_target]

    def ensure_pane_state(self, tmux_target: str, pane_id: str) -> PaneState:
        ts = self._bot_state.topics.get(tmux_target)
        if ts is None:
            return PaneState(pane_id=pane_id)
        if pane_id not in ts.panes:
            ts.panes[pane_id] = PaneState(pane_id=pane_id)
        return ts.panes[pane_id]

    def remove_topic(self, tmux_target: str) -> None:
        self._bot_state.topics.pop(tmux_target, None)
        self.save()

    # -- Tool message tracking --

    def set_tool_msg_id(self, pane_id: str, tool_use_id: str, msg_id: int) -> None:
        for ts in self._bot_state.topics.values():
            ps = ts.panes.get(pane_id)
            if ps is not None:
                ps.tool_msg_ids[tool_use_id] = msg_id
                return

    def get_tool_msg_id(self, pane_id: str, tool_use_id: str) -> int | None:
        for ts in self._bot_state.topics.values():
            ps = ts.panes.get(pane_id)
            if ps is not None:
                return ps.tool_msg_ids.get(tool_use_id)
        return None

    # -- Action bar --

    def set_action_bar_msg_id(self, topic_id: int, msg_id: int) -> None:
        for ts in self._bot_state.topics.values():
            if ts.topic_id == topic_id:
                ts.action_bar_msg_id = msg_id
                self.save()
                return

    def get_action_bar_msg_id(self, topic_id: int) -> int | None:
        for ts in self._bot_state.topics.values():
            if ts.topic_id == topic_id:
                return ts.action_bar_msg_id
        return None

    # -- Caffeinate --

    async def start_caffeinate(self) -> None:
        if self._caffeinate_proc is not None:
            return
        self._caffeinate_proc = subprocess.Popen(
            ["caffeinate", "-i"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._bot_state.caffeinate_active = True
        self.save()
        logger.info("Caffeinate started (pid=%d)", self._caffeinate_proc.pid)

    async def stop_caffeinate(self) -> None:
        if self._caffeinate_proc is not None:
            self._caffeinate_proc.terminate()
            self._caffeinate_proc = None
        self._bot_state.caffeinate_active = False
        self.save()
        logger.info("Caffeinate stopped")

    # -- Pane iteration --

    def find_pane_state(self, pane_id: str) -> PaneState | None:
        for ts in self._bot_state.topics.values():
            ps = ts.panes.get(pane_id)
            if ps is not None:
                return ps
        return None

    def all_pane_ids(self) -> list[str]:
        result: list[str] = []
        for ts in self._bot_state.topics.values():
            result.extend(ts.panes.keys())
        return result

    def get_topic_id_for_pane(self, pane_id: str) -> int | None:
        for ts in self._bot_state.topics.values():
            if pane_id in ts.panes:
                return ts.topic_id
        return None
