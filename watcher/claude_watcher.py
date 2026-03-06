from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from aiogram import Bot

from bot import keyboards
from bot.formatters import (
    format_stop_event,
    format_subagent_start,
    format_subagent_stop,
    format_thinking_block,
    format_tool_failure,
    format_tool_running,
    format_tool_result,
    format_transcript_entry,
)
from claude.hooks import (
    HookEventWatcher,
    parse_stop_event,
    parse_subagent_event,
    parse_tool_result,
    parse_tool_use,
)
from claude.models import HookEvent, HookPayload

if TYPE_CHECKING:
    from watcher.state import StateManager

logger = logging.getLogger(__name__)


class ClaudeWatcher:
    def __init__(
        self,
        bot: Bot,
        chat_id: int,
        state: StateManager,
    ) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._state = state
        self._hook_watcher = HookEventWatcher(self._on_hook_event)
        self._claude_active_panes: set[str] = set()

    async def start(self) -> None:
        logger.info("Claude watcher started")
        await self._hook_watcher.start()

    def stop(self) -> None:
        self._hook_watcher.stop()

    def is_claude_active(self, pane_id: str) -> bool:
        return pane_id in self._claude_active_panes

    async def _on_hook_event(self, payload: HookPayload) -> None:
        pane_id = payload.pane_id
        topic_id = self._state.get_topic_id_for_pane(pane_id)

        # Mark pane as Claude pane
        if pane_id and pane_id != "unknown":
            self._state.mark_claude_pane(pane_id, True)

        if topic_id is None:
            logger.debug("No topic for pane %s, skipping event %s", pane_id, payload.event)
            return

        if payload.event == HookEvent.PRE_TOOL_USE:
            await self._handle_pre_tool_use(payload, topic_id, pane_id)
        elif payload.event == HookEvent.POST_TOOL_USE:
            await self._handle_post_tool_use(payload, topic_id, pane_id)
        elif payload.event == HookEvent.POST_TOOL_USE_FAILURE:
            await self._handle_tool_failure(payload, topic_id, pane_id)
        elif payload.event == HookEvent.STOP:
            await self._handle_stop(payload, topic_id, pane_id)
        elif payload.event == HookEvent.NOTIFICATION:
            await self._handle_notification(payload, topic_id)
        elif payload.event == HookEvent.SESSION_START:
            self._claude_active_panes.add(pane_id)
            await self._update_action_bar(topic_id, claude_active=True)
        elif payload.event == HookEvent.SESSION_END:
            self._claude_active_panes.discard(pane_id)
            await self._update_action_bar(topic_id, claude_active=False)
        elif payload.event == HookEvent.USER_PROMPT_SUBMIT:
            self._claude_active_panes.add(pane_id)
            await self._update_action_bar(topic_id, claude_active=True)
        elif payload.event == HookEvent.SUBAGENT_START:
            event = parse_subagent_event(payload)
            await self._bot.send_message(
                chat_id=self._chat_id,
                message_thread_id=topic_id,
                text=format_subagent_start(event.description),
            )
        elif payload.event == HookEvent.SUBAGENT_STOP:
            await self._bot.send_message(
                chat_id=self._chat_id,
                message_thread_id=topic_id,
                text=format_subagent_stop(),
            )

    async def _handle_pre_tool_use(
        self, payload: HookPayload, topic_id: int, pane_id: str
    ) -> None:
        event = parse_tool_use(payload)
        text = format_tool_running(event)
        msg = await self._bot.send_message(
            chat_id=self._chat_id,
            message_thread_id=topic_id,
            text=text,
        )
        self._state.set_tool_msg_id(pane_id, event.tool_use_id, msg.message_id)

    async def _handle_post_tool_use(
        self, payload: HookPayload, topic_id: int, pane_id: str
    ) -> None:
        event = parse_tool_result(payload)
        text = format_tool_result(event)

        # Edit the original "tool running" message
        msg_id = self._state.get_tool_msg_id(pane_id, event.tool_use_id)
        if msg_id:
            try:
                await self._bot.edit_message_text(
                    chat_id=self._chat_id,
                    message_id=msg_id,
                    text=text,
                )
                return
            except Exception:
                logger.debug("Failed to edit tool message, sending new one")

        await self._bot.send_message(
            chat_id=self._chat_id,
            message_thread_id=topic_id,
            text=text,
        )

    async def _handle_tool_failure(
        self, payload: HookPayload, topic_id: int, pane_id: str
    ) -> None:
        event = parse_tool_result(payload)
        text = format_tool_failure(event)

        msg_id = self._state.get_tool_msg_id(pane_id, event.tool_use_id)
        if msg_id:
            try:
                await self._bot.edit_message_text(
                    chat_id=self._chat_id,
                    message_id=msg_id,
                    text=text,
                )
                return
            except Exception:
                pass

        await self._bot.send_message(
            chat_id=self._chat_id,
            message_thread_id=topic_id,
            text=text,
        )

    async def _handle_stop(
        self, payload: HookPayload, topic_id: int, pane_id: str
    ) -> None:
        event = parse_stop_event(payload)
        self._claude_active_panes.discard(pane_id)
        text = format_stop_event(event)
        await self._bot.send_message(
            chat_id=self._chat_id,
            message_thread_id=topic_id,
            text=text,
        )
        await self._update_action_bar(topic_id, claude_active=False)

    async def _handle_notification(
        self, payload: HookPayload, topic_id: int
    ) -> None:
        notification_type = payload.data.get("type", "")
        title = payload.data.get("title", "Notification")
        body = payload.data.get("body", "")

        if notification_type == "permission_prompt":
            text = body or "Claude is asking for permission..."
            await self._bot.send_message(
                chat_id=self._chat_id,
                message_thread_id=topic_id,
                text=text,
                reply_markup=keyboards.permission_keyboard(),
            )
        elif notification_type == "idle_prompt":
            await self._bot.send_message(
                chat_id=self._chat_id,
                message_thread_id=topic_id,
                text="Claude is waiting for input.",
            )
        else:
            text = f"{title}: {body}" if body else title
            await self._bot.send_message(
                chat_id=self._chat_id,
                message_thread_id=topic_id,
                text=text,
            )

    async def _update_action_bar(self, topic_id: int, claude_active: bool) -> None:
        msg_id = self._state.get_action_bar_msg_id(topic_id)
        kb = keyboards.action_bar_keyboard(claude_active=claude_active)

        if msg_id:
            try:
                await self._bot.edit_message_reply_markup(
                    chat_id=self._chat_id,
                    message_id=msg_id,
                    reply_markup=kb,
                )
                return
            except Exception:
                logger.debug("Failed to edit action bar, creating new one")

        msg = await self._bot.send_message(
            chat_id=self._chat_id,
            message_thread_id=topic_id,
            text="Action Bar",
            reply_markup=kb,
        )
        self._state.set_action_bar_msg_id(topic_id, msg.message_id)
