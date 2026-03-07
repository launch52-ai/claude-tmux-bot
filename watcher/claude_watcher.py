from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter

from bot import keyboards
from bot.formatters import (
    format_hook_tool_use,
    format_stop_event,
    format_tool_failure,
    format_transcript_entry,
)
from claude.hooks import (
    HookEventWatcher,
    parse_stop_event,
    parse_tool_result,
    parse_tool_use,
)
from claude.models import HookEvent, HookPayload, TranscriptRole
from claude.transcript import TranscriptReader, find_transcript_files

if TYPE_CHECKING:
    from watcher.state import StateManager

logger = logging.getLogger(__name__)

_TRANSCRIPT_POLL_INTERVAL = 2.0


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
        self._transcript_readers: dict[str, TranscriptReader] = {}
        # session_id -> topic_id, so the transcript poller knows where to send
        self._session_topics: dict[str, int] = {}
        self._running = False

    async def start(self) -> None:
        logger.info("Claude watcher started")
        self._running = True
        await asyncio.gather(
            self._hook_watcher.start(),
            self._transcript_poll_loop(),
        )

    def stop(self) -> None:
        self._running = False
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

        # Always try to init transcript reader on any event with a session_id
        if payload.session_id:
            transcript_path = payload.data.get("transcript_path")
            self._init_transcript_reader(payload.session_id, topic_id, transcript_path)

        if payload.event == HookEvent.PRE_TOOL_USE:
            await self._handle_tool_use(payload, topic_id)
        elif payload.event == HookEvent.POST_TOOL_USE_FAILURE:
            await self._handle_tool_failure(payload, topic_id, pane_id)
        elif payload.event == HookEvent.STOP:
            await self._handle_stop(payload, topic_id, pane_id)
        elif payload.event == HookEvent.NOTIFICATION:
            await self._handle_notification(payload, topic_id)
        elif payload.event == HookEvent.SESSION_START:
            self._claude_active_panes.add(pane_id)
            self._init_transcript_reader(payload.session_id, topic_id)
            await self._update_action_bar(topic_id, claude_active=True)
        elif payload.event == HookEvent.SESSION_END:
            self._claude_active_panes.discard(pane_id)
            self._cleanup_session(payload.session_id)
            await self._update_action_bar(topic_id, claude_active=False)
        elif payload.event == HookEvent.USER_PROMPT_SUBMIT:
            self._claude_active_panes.add(pane_id)
            self._init_transcript_reader(payload.session_id, topic_id)
            await self._send_typing_indicator(topic_id)
            await self._update_action_bar(topic_id, claude_active=True)

    async def _handle_tool_use(
        self, payload: HookPayload, topic_id: int
    ) -> None:
        event = parse_tool_use(payload)
        cwd = payload.data.get("cwd", "")
        text = format_hook_tool_use(event, cwd)
        await self._send_transcript_message(
            topic_id, text, reply_markup=keyboards.action_bar_keyboard(claude_active=True),
        )

    async def _handle_tool_failure(
        self, payload: HookPayload, topic_id: int, pane_id: str
    ) -> None:
        event = parse_tool_result(payload)
        text = format_tool_failure(event)
        await self._bot.send_message(
            chat_id=self._chat_id,
            message_thread_id=topic_id,
            text=text,
        )

    async def _handle_stop(
        self, payload: HookPayload, topic_id: int, pane_id: str
    ) -> None:
        # Flush any remaining transcript entries
        await self._flush_transcript(payload.session_id, topic_id)

        event = parse_stop_event(payload)
        self._claude_active_panes.discard(pane_id)
        self._cleanup_session(payload.session_id)
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
            tool_name = payload.data.get("tool_name", "")
            always_text = f"Always allow {tool_name}" if tool_name else "Always Allow"
            await self._bot.send_message(
                chat_id=self._chat_id,
                message_thread_id=topic_id,
                text=text,
                reply_markup=keyboards.permission_keyboard(always_text),
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
        text = "Claude is working..." if claude_active else "Claude is idle."

        if msg_id:
            try:
                await self._bot.edit_message_text(
                    chat_id=self._chat_id,
                    message_id=msg_id,
                    text=text,
                    reply_markup=kb,
                )
                return
            except Exception:
                logger.debug("Failed to edit action bar, creating new one")

        msg = await self._bot.send_message(
            chat_id=self._chat_id,
            message_thread_id=topic_id,
            text=text,
            reply_markup=kb,
        )
        self._state.set_action_bar_msg_id(topic_id, msg.message_id)

    async def _send_typing_indicator(self, topic_id: int) -> None:
        try:
            await self._bot.send_chat_action(
                chat_id=self._chat_id,
                action="typing",
                message_thread_id=topic_id,
            )
        except Exception:
            logger.debug("Failed to send typing indicator")

    def _init_transcript_reader(
        self, session_id: str, topic_id: int, transcript_path: str | None = None
    ) -> None:
        if not session_id:
            return
        self._session_topics[session_id] = topic_id
        if session_id in self._transcript_readers:
            return

        # Use provided path or search for it
        filepath: Path | None = None
        if transcript_path:
            p = Path(transcript_path)
            if p.exists():
                filepath = p
        if filepath is None:
            files = find_transcript_files(session_id)
            if files:
                filepath = files[0]

        if filepath:
            reader = TranscriptReader(filepath)
            # Skip to end so we only get new content from this point
            reader.read_new_entries()
            self._transcript_readers[session_id] = reader
            logger.info("Initialized transcript reader for session %s: %s", session_id, filepath)

    def _cleanup_session(self, session_id: str) -> None:
        self._transcript_readers.pop(session_id, None)
        self._session_topics.pop(session_id, None)

    async def _transcript_poll_loop(self) -> None:
        """Periodically flush transcript entries for all active sessions."""
        while self._running:
            for session_id, topic_id in list(self._session_topics.items()):
                await self._flush_transcript(session_id, topic_id)
            await asyncio.sleep(_TRANSCRIPT_POLL_INTERVAL)

    async def _flush_transcript(self, session_id: str, topic_id: int) -> None:
        reader = self._transcript_readers.get(session_id)
        if reader is None:
            self._init_transcript_reader(session_id, topic_id)
            reader = self._transcript_readers.get(session_id)
            if reader is None:
                return

        entries = reader.read_new_entries()
        for entry in entries:
            if entry.role != TranscriptRole.ASSISTANT:
                continue
            messages = format_transcript_entry(entry)
            for text in messages:
                if not text.strip():
                    continue
                await self._send_transcript_message(topic_id, text)

    async def _send_transcript_message(
        self, topic_id: int, text: str, reply_markup: object = None,
    ) -> None:
        for attempt in range(3):
            try:
                await self._bot.send_message(
                    chat_id=self._chat_id,
                    message_thread_id=topic_id,
                    text=text,
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
                return
            except TelegramRetryAfter as e:
                logger.debug("Rate limited, waiting %ss", e.retry_after)
                await asyncio.sleep(e.retry_after)
            except Exception:
                # HTML parse error — try without formatting once, then give up
                try:
                    await self._bot.send_message(
                        chat_id=self._chat_id,
                        message_thread_id=topic_id,
                        text=text,
                        reply_markup=reply_markup,
                    )
                except TelegramRetryAfter as e:
                    await asyncio.sleep(e.retry_after)
                except Exception:
                    logger.debug("Failed to send transcript message")
                return
