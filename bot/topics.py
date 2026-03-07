from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiogram import Bot

if TYPE_CHECKING:
    from tmux.manager import SessionInfo

logger = logging.getLogger(__name__)


class TopicManager:
    def __init__(
        self,
        bot: Bot,
        chat_id: int,
        topic_mode: str = "session",
        topic_cleanup: str = "close",
    ) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._topic_mode = topic_mode
        self._topic_cleanup = topic_cleanup  # "close" or "delete"
        # tmux_target (session_id or session_id:window_id) -> topic_id
        self._topic_map: dict[str, int] = {}
        # topic_id -> tmux_target
        self._reverse_map: dict[int, str] = {}
        # tmux_target -> display name (for rename detection)
        self._display_names: dict[str, str] = {}
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
        display_names: dict[str, str] | None = None,
    ) -> None:
        self._topic_map = dict(topic_map)
        self._reverse_map = {v: k for k, v in topic_map.items()}
        self._control_topic_id = control_topic_id
        self._topic_mode = topic_mode
        self._display_names = dict(display_names) if display_names else {}

    def get_state(self) -> dict:
        return {
            "topic_map": dict(self._topic_map),
            "control_topic_id": self._control_topic_id,
            "topic_mode": self._topic_mode,
            "display_names": dict(self._display_names),
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
        target = session.session_id
        existing = self._topic_map.get(target)
        if existing is not None:
            return existing

        topic_name = f"{session.session_index}-{session.session_name}"
        topic = await self._bot.create_forum_topic(
            chat_id=self._chat_id,
            name=topic_name,
        )
        topic_id = topic.message_thread_id
        self._topic_map[target] = topic_id
        self._reverse_map[topic_id] = target
        self._display_names[target] = topic_name
        logger.info("Created topic '%s' -> %d", topic_name, topic_id)
        return topic_id

    async def create_topic_for_window(
        self,
        session_id: str,
        session_index: int,
        session_name: str,
        window_id: str,
        window_index: int,
        window_name: str,
    ) -> int:
        target = f"{session_id}:{window_id}"
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
        self._display_names[target] = topic_name
        logger.info("Created topic '%s' -> %d", topic_name, topic_id)
        return topic_id

    async def sync_sessions(self, sessions: list[SessionInfo]) -> None:
        if self._topic_mode == "session":
            await self._sync_session_mode(sessions)
        else:
            await self._sync_window_mode(sessions)

    async def _sync_session_mode(self, sessions: list[SessionInfo]) -> None:
        current_ids = {s.session_id for s in sessions}

        for session in sessions:
            target = session.session_id
            if target not in self._topic_map:
                await self.create_topic_for_session(session)
            else:
                # Check for rename
                new_name = f"{session.session_index}-{session.session_name}"
                await self._rename_if_needed(target, new_name)

        # Archive stale topics
        for target in list(self._topic_map.keys()):
            if target not in current_ids:
                await self._archive_topic(target)

    async def _sync_window_mode(self, sessions: list[SessionInfo]) -> None:
        current_targets: set[str] = set()
        for session in sessions:
            for window in session.windows:
                target = f"{session.session_id}:{window.window_id}"
                current_targets.add(target)
                if target not in self._topic_map:
                    await self.create_topic_for_window(
                        session_id=session.session_id,
                        session_index=session.session_index,
                        session_name=session.session_name,
                        window_id=window.window_id,
                        window_index=window.window_index,
                        window_name=window.window_name,
                    )
                else:
                    new_name = f"{session.session_index}-{session.session_name}-{window.window_index}-{window.window_name}"
                    await self._rename_if_needed(target, new_name)

        for target in list(self._topic_map.keys()):
            if target not in current_targets:
                await self._archive_topic(target)

    async def _rename_if_needed(self, target: str, new_name: str) -> None:
        old_name = self._display_names.get(target)
        if old_name == new_name:
            return

        topic_id = self._topic_map.get(target)
        if topic_id is None:
            return

        try:
            await self._bot.edit_forum_topic(
                chat_id=self._chat_id,
                message_thread_id=topic_id,
                name=new_name,
            )
            logger.info("Renamed topic '%s' -> '%s'", old_name, new_name)
        except Exception:
            logger.warning("Failed to rename topic '%s' -> '%s'", old_name, new_name)
        # Always update to prevent retry loop on persistent failure
        self._display_names[target] = new_name

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
            self._display_names.pop(target, None)
            try:
                if self._topic_cleanup == "delete":
                    await self._bot.delete_forum_topic(
                        chat_id=self._chat_id,
                        message_thread_id=topic_id,
                    )
                    logger.info("Deleted topic for '%s'", target)
                else:
                    await self._bot.close_forum_topic(
                        chat_id=self._chat_id,
                        message_thread_id=topic_id,
                    )
                    logger.info("Closed topic for '%s'", target)
            except Exception:
                logger.warning("Failed to archive topic for '%s'", target)
