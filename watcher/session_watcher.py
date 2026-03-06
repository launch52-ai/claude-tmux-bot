from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from aiogram import Bot

if TYPE_CHECKING:
    from bot.topics import TopicManager
    from tmux.manager import TmuxManager
    from watcher.state import StateManager

logger = logging.getLogger(__name__)


class SessionWatcher:
    def __init__(
        self,
        bot: Bot,
        chat_id: int,
        tmux: TmuxManager,
        topics: TopicManager,
        state: StateManager,
        poll_interval: float = 5.0,
    ) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._tmux = tmux
        self._topics = topics
        self._state = state
        self._poll_interval = poll_interval
        self._running = False
        self._known_sessions: set[str] = set()
        self._known_windows: set[str] = set()
        self._last_poll_time: float = 0.0
        self._wake_threshold: float = poll_interval * 6  # 30s for 5s interval

    async def start(self) -> None:
        self._running = True
        self._last_poll_time = time.monotonic()
        # Initial snapshot
        self._refresh_known()
        logger.info("Session watcher started")

        while self._running:
            try:
                now = time.monotonic()
                gap = now - self._last_poll_time
                self._last_poll_time = now

                if gap > self._wake_threshold:
                    await self._handle_wake(gap)

                await self._poll()
            except Exception:
                logger.exception("Session watcher error")
            await asyncio.sleep(self._poll_interval)

    def stop(self) -> None:
        self._running = False

    def _refresh_known(self) -> None:
        try:
            sessions = self._tmux.list_sessions()
            self._known_sessions = {s.session_name for s in sessions}
            self._known_windows = set()
            for s in sessions:
                for w in s.windows:
                    self._known_windows.add(f"{s.session_name}:{w.window_name}")
        except Exception:
            logger.exception("Failed to refresh known sessions")

    async def _poll(self) -> None:
        if not self._tmux.is_available():
            logger.warning("tmux server not available")
            return

        sessions = self._tmux.list_sessions()
        current_sessions = {s.session_name for s in sessions}
        current_windows: set[str] = set()
        for s in sessions:
            for w in s.windows:
                current_windows.add(f"{s.session_name}:{w.window_name}")

        # Detect new sessions
        new_sessions = current_sessions - self._known_sessions
        removed_sessions = self._known_sessions - current_sessions

        # Detect new windows
        new_windows = current_windows - self._known_windows
        removed_windows = self._known_windows - current_windows

        if new_sessions or removed_sessions or new_windows or removed_windows:
            await self._topics.sync_sessions(sessions)

            # Register panes for new sessions/windows
            for session in sessions:
                if self._topics.topic_mode == "session":
                    target = session.session_name
                    topic_id = self._topics.get_topic_id(target)
                    if topic_id is not None:
                        ts = self._state.ensure_topic_state(target, topic_id)
                        for window in session.windows:
                            for pane in window.panes:
                                self._state.ensure_pane_state(target, pane.pane_id)
                                # Auto-focus first pane if none focused
                                if not ts.focused_pane_id:
                                    self._state.set_focused_pane(topic_id, pane.pane_id)
                else:
                    for window in session.windows:
                        target = f"{session.session_name}:{window.window_name}"
                        topic_id = self._topics.get_topic_id(target)
                        if topic_id is not None:
                            ts = self._state.ensure_topic_state(target, topic_id)
                            for pane in window.panes:
                                self._state.ensure_pane_state(target, pane.pane_id)
                                if not ts.focused_pane_id:
                                    self._state.set_focused_pane(topic_id, pane.pane_id)

            # Notify control topic about changes
            control_id = self._topics.control_topic_id
            if control_id:
                for name in new_sessions:
                    await self._bot.send_message(
                        chat_id=self._chat_id,
                        message_thread_id=control_id,
                        text=f"New session detected: {name}",
                    )
                for name in removed_sessions:
                    await self._bot.send_message(
                        chat_id=self._chat_id,
                        message_thread_id=control_id,
                        text=f"Session ended: {name}",
                    )

            # Clean up state for removed sessions
            for name in removed_sessions:
                self._state.remove_topic(name)
            for target in removed_windows:
                self._state.remove_topic(target)

            self._state.save()

        self._known_sessions = current_sessions
        self._known_windows = current_windows

    async def _handle_wake(self, gap: float) -> None:
        minutes = int(gap / 60)
        logger.info("Detected wake from sleep (gap: %ds)", int(gap))

        # Re-discover sessions from scratch
        self._refresh_known()

        # Full re-sync
        if self._tmux.is_available():
            sessions = self._tmux.list_sessions()
            await self._topics.sync_sessions(sessions)

        # Notify control topic
        control_id = self._topics.control_topic_id
        if control_id:
            duration = f"{minutes}m" if minutes > 0 else f"{int(gap)}s"
            await self._bot.send_message(
                chat_id=self._chat_id,
                message_thread_id=control_id,
                text=f"Resumed after ~{duration} sleep. Sessions re-synced.",
            )
