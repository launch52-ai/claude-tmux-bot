from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiogram import Bot

if TYPE_CHECKING:
    from tmux.manager import SessionInfo

logger = logging.getLogger(__name__)


class TopicManager:
    def __init__(self, bot: Bot, chat_id: int, topic_mode: str = "session") -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._topic_mode = topic_mode
        # tmux_target -> topic_id
        self._topic_map: dict[str, int] = {}
        # topic_id -> tmux_target
        self._reverse_map: dict[int, str] = {}
        self._control_topic_id: int | None = None

    @property
    def topic_mode(self) -> str:
        return self._topic_mode

    @property
    def control_topic_id(self) -> int | None:
        return self._control_topic_id

    def get_topic_id(self, tmux_target: str) -> int | None:
        return self._topic_map.get(tmux_target)

    def get_tmux_target(self, topic_id: int) -> str | None:
        return self._reverse_map.get(topic_id)

    def is_control_topic(self, topic_id: int) -> bool:
        return topic_id == self._control_topic_id

    def all_targets(self) -> list[str]:
        return list(self._topic_map.keys())

    def load_state(
        self,
        topic_map: dict[str, int],
        control_topic_id: int | None,
        topic_mode: str,
    ) -> None:
        self._topic_map = dict(topic_map)
        self._reverse_map = {v: k for k, v in topic_map.items()}
        self._control_topic_id = control_topic_id
        self._topic_mode = topic_mode

    def get_state(self) -> dict:
        return {
            "topic_map": dict(self._topic_map),
            "control_topic_id": self._control_topic_id,
            "topic_mode": self._topic_mode,
        }

    async def ensure_control_topic(self) -> int:
        if self._control_topic_id is not None:
            return self._control_topic_id
        topic = await self._bot.create_forum_topic(
            chat_id=self._chat_id,
            name="Control",
        )
        self._control_topic_id = topic.message_thread_id
        logger.info("Created Control topic: %d", self._control_topic_id)
        return self._control_topic_id

    async def create_topic_for_session(self, session: SessionInfo) -> int:
        target = session.session_name
        existing = self._topic_map.get(target)
        if existing is not None:
            return existing

        topic = await self._bot.create_forum_topic(
            chat_id=self._chat_id,
            name=session.session_name,
        )
        topic_id = topic.message_thread_id
        self._topic_map[target] = topic_id
        self._reverse_map[topic_id] = target
        logger.info("Created topic '%s' -> %d", target, topic_id)
        return topic_id

    async def create_topic_for_window(
        self,
        session_index: int,
        session_name: str,
        window_index: int,
        window_name: str,
    ) -> int:
        target = f"{session_name}:{window_name}"
        existing = self._topic_map.get(target)
        if existing is not None:
            return existing

        topic_name = f"{session_index}-{session_name}-{window_index}-{window_name}"
        topic = await self._bot.create_forum_topic(
            chat_id=self._chat_id,
            name=topic_name,
        )
        topic_id = topic.message_thread_id
        self._topic_map[target] = topic_id
        self._reverse_map[topic_id] = target
        logger.info("Created topic '%s' -> %d", topic_name, topic_id)
        return topic_id

    async def sync_sessions(self, sessions: list[SessionInfo]) -> None:
        if self._topic_mode == "session":
            await self._sync_session_mode(sessions)
        else:
            await self._sync_window_mode(sessions)

    async def _sync_session_mode(self, sessions: list[SessionInfo]) -> None:
        current_names = {s.session_name for s in sessions}

        # Create topics for new sessions
        for session in sessions:
            if session.session_name not in self._topic_map:
                await self.create_topic_for_session(session)

        # Archive stale topics
        for target in list(self._topic_map.keys()):
            if target not in current_names:
                await self._archive_topic(target)

    async def _sync_window_mode(self, sessions: list[SessionInfo]) -> None:
        current_targets: set[str] = set()
        for session in sessions:
            for window in session.windows:
                target = f"{session.session_name}:{window.window_name}"
                current_targets.add(target)
                if target not in self._topic_map:
                    await self.create_topic_for_window(
                        session_index=session.session_index,
                        session_name=session.session_name,
                        window_index=window.window_index,
                        window_name=window.window_name,
                    )

        for target in list(self._topic_map.keys()):
            if target not in current_targets:
                await self._archive_topic(target)

    async def switch_mode(self, new_mode: str, sessions: list[SessionInfo]) -> None:
        if new_mode == self._topic_mode:
            return

        # Archive all current topics
        for target in list(self._topic_map.keys()):
            await self._archive_topic(target)

        self._topic_mode = new_mode
        await self.sync_sessions(sessions)

    async def _archive_topic(self, target: str) -> None:
        topic_id = self._topic_map.pop(target, None)
        if topic_id is not None:
            self._reverse_map.pop(topic_id, None)
            try:
                await self._bot.close_forum_topic(
                    chat_id=self._chat_id,
                    message_thread_id=topic_id,
                )
                logger.info("Archived topic for '%s'", target)
            except Exception:
                logger.warning("Failed to archive topic for '%s'", target)
